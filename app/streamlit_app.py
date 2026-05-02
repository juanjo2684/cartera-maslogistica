"""Dashboard de Gestión de Cartera — +logística.

Vistas:
  1. Estado de cartera — KPIs, distribución, tabla filtrable.
  2. Excepciones por resolver — formularios que persisten decisiones.
  3. Decisiones registradas — auditoría con acción REVERTIR.
  4. Generar correos de seguimiento — copy listo para enviar por cliente.

Ejecutar desde la raíz: streamlit run app/streamlit_app.py
"""

import os
import sys
from ast import literal_eval
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

import altair as alt
import pandas as pd
import streamlit as st

from registro_decisiones import (
    agregar_alias,
    cargar_decisiones,
    decisiones_activas_detalle,
    generar_huella_pago,
    registrar_decision,
    revertir_decision,
)
from plantillas_correos import construir_correo

st.set_page_config(page_title="Cartera +logística", page_icon="💼", layout="wide")

RUTA_BASE = "data/output/base_consolidada.csv"
RUTA_EXCEPCIONES = "data/output/excepciones.csv"
RUTA_HISTORIAL = "data/output/historial_pagos.csv"


# -----------------------------------------------------------------------------
# Utilidades
# -----------------------------------------------------------------------------


@st.cache_data
def cargar_base(ruta: str = RUTA_BASE) -> pd.DataFrame:
    if not Path(ruta).exists():
        return pd.DataFrame()
    return pd.read_csv(
        ruta,
        parse_dates=["fecha_vencimiento", "fecha_contabilizacion", "fecha_pago"],
    )


@st.cache_data
def cargar_excepciones(ruta: str = RUTA_EXCEPCIONES) -> pd.DataFrame:
    if not Path(ruta).exists():
        return pd.DataFrame()
    df = pd.read_csv(ruta, parse_dates=["fecha"])
    if "facturas_asociadas" in df.columns:
        df["facturas_asociadas"] = df["facturas_asociadas"].apply(_parsear_lista_segura)
    return df


def _parsear_lista_segura(valor):
    """Convierte un string '[A, B]' a lista. Tolerante a NaN/vacíos."""
    if pd.isna(valor) or valor == "" or valor == "[]":
        return []
    try:
        res = literal_eval(valor)
        return list(res) if isinstance(res, (list, tuple)) else []
    except (ValueError, SyntaxError):
        return []


@st.cache_data
def contar_omitidos_ultima_corrida(ruta: str = RUTA_HISTORIAL) -> int:
    """Pagos persistidos en la corrida más reciente (todos comparten timestamp)."""
    if not Path(ruta).exists():
        return 0
    df = pd.read_csv(ruta, usecols=["fecha_corrida"])
    if df.empty:
        return 0
    ultima = df["fecha_corrida"].max()
    return int((df["fecha_corrida"] == ultima).sum())


def formato_cop(valor) -> str:
    """Formatea un número como moneda colombiana."""
    try:
        return f"${valor:,.0f}"
    except (TypeError, ValueError):
        return "—"


def _campo(label: str, valor) -> str | None:
    """Devuelve 'label: valor' si valor es no vacío, o None para omitir."""
    if pd.isna(valor):
        return None
    s = str(valor).strip()
    return f"**{label}:** {s}" if s else None


def _mapa_huella_a_fecha_decision() -> dict[str, str]:
    """Mapa huella_pago → fecha_decision, para enriquecer las tarjetas de excepción.

    Las excepciones que ya tienen decisión registrada (PAGO_PARCIAL, CLIENTE_NUEVO,
    PENDIENTE) reaparecen cada corrida. Mostrar la fecha de la última decisión
    le indica a la analista que el caso ya está procesado y por qué reaparece.
    """
    try:
        df_dec = cargar_decisiones()
    except Exception:
        return {}
    if df_dec.empty:
        return {}
    # Última decisión registrada por huella (más reciente).
    df_dec = df_dec.sort_values("fecha_decision").drop_duplicates(
        subset=["huella_pago"], keep="last"
    )
    return {
        str(h): str(f) for h, f in zip(df_dec["huella_pago"], df_dec["fecha_decision"])
    }


def _badge_html(texto: str) -> str:
    """Insignia inline para mostrar al lado del título de una tarjeta."""
    return (
        f'<span style="display:inline-block; padding:2px 10px; '
        f"background:#f0f2f6; border:1px solid #d0d4dc; border-radius:12px; "
        f'font-size:0.85em; color:#31333f;">{texto}</span>'
    )


# -----------------------------------------------------------------------------
# Sidebar
# -----------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### 💼 Cartera +logística")
    st.caption("MVP — Reto 10 · Beca SER ANDI")

    vista = st.radio(
        "Vista",
        [
            "📊 Estado de cartera",
            "⚠️ Excepciones por resolver",
            "📜 Decisiones registradas",
            "📧 Generar correos de seguimiento",
        ],
        label_visibility="collapsed",
    )

    st.divider()

    if st.button("🔄 Recargar datos", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()

    if Path(RUTA_BASE).exists():
        ts = pd.Timestamp.fromtimestamp(Path(RUTA_BASE).stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M"
        )
        st.caption(f"**Última actualización:**\n\n{ts}")
    else:
        st.warning("Aún no hay datos. Corre `python run_pipeline.py` primero.")

    try:
        df_dec = cargar_decisiones()
        if not df_dec.empty:
            st.caption(
                f"📝 **Decisiones registradas:** {len(df_dec)}\n\n"
                "_Se aplicarán en la próxima corrida del pipeline._"
            )
    except Exception:
        pass

    try:
        n_omitidos = contar_omitidos_ultima_corrida()
        st.caption(
            f"📋 **Pagos omitidos (última corrida):** {n_omitidos}\n\n"
            "_Pagos ya conciliados en corridas anteriores._"
        )
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Vista 1 — Estado de cartera
# -----------------------------------------------------------------------------

ORDEN_BANDAS = ["AL_DIA", "0-30", "31-60", "61-90", "91-120", "121+"]
ORDEN_PRIORIDAD = {"CRITICO": 0, "ALTO": 1, "MEDIO": 2, "BAJO": 3, "RESUELTO": 4}


def _clientes_con_cartera_abierta(base: pd.DataFrame) -> pd.DataFrame:
    """Agrega la base por cliente sobre facturas abiertas.

    Devuelve: cliente, n_facturas, saldo_total, dias_max_vencido, banda_mas_vencida.
    Ordenado por dias_max_vencido descendente (críticos primero).
    """
    if base.empty:
        return pd.DataFrame(
            columns=[
                "cliente",
                "n_facturas",
                "saldo_total",
                "dias_max_vencido",
                "banda_mas_vencida",
            ]
        )

    abiertas = base[~base["tiene_pago_aplicado"]]
    if abiertas.empty:
        return pd.DataFrame(
            columns=[
                "cliente",
                "n_facturas",
                "saldo_total",
                "dias_max_vencido",
                "banda_mas_vencida",
            ]
        )

    def _peor_banda(serie: pd.Series) -> str:
        presentes = set(serie.dropna().astype(str).unique())
        for banda in reversed(ORDEN_BANDAS):
            if banda in presentes:
                return banda
        return "AL_DIA"

    return (
        abiertas.groupby("cliente")
        .agg(
            n_facturas=("documento", "count"),
            saldo_total=("saldo_pendiente", "sum"),
            dias_max_vencido=("dias_vencido", "max"),
            banda_mas_vencida=("banda_antiguedad", _peor_banda),
        )
        .reset_index()
        .sort_values("dias_max_vencido", ascending=False)
        .reset_index(drop=True)
    )


def render_estado_cartera():
    st.title("📊 Estado de cartera")

    base = cargar_base()
    if base.empty:
        st.warning("No hay base consolidada. Ejecuta el pipeline primero.")
        return

    # Aviso si la corrida absorbió pagos del historial — explica por qué
    # "Pagos aplicados" puede verse bajo aunque el sistema esté funcionando.
    n_omitidos = contar_omitidos_ultima_corrida()
    if n_omitidos > 0:
        st.caption(
            f"📋 {n_omitidos} pago(s) previamente conciliado(s) en SAP fueron omitidos en esta corrida. "
            "Esto explica por qué 'Pagos aplicados hoy' puede verse bajo: "
            "los pagos ya conciliados no se reaplican."
        )
    # ---- KPIs ----
    abiertas = base[~base["tiene_pago_aplicado"]]
    saldo_total = abiertas["saldo_pendiente"].sum()
    criticas = abiertas[abiertas["prioridad"] == "CRITICO"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💰 Saldo pendiente", formato_cop(saldo_total))
    c2.metric("📄 Facturas abiertas", f"{len(abiertas)}")
    c3.metric(
        "🔴 Cartera crítica",
        formato_cop(criticas["saldo_pendiente"].sum()),
        delta=f"{len(criticas)} facturas" if len(criticas) else "sin casos",
        delta_color="inverse",
    )
    c4.metric("✅ Pagos aplicados hoy", f"{base['tiene_pago_aplicado'].sum()}")

    st.divider()

    # ---- Distribución por banda ----
    st.subheader("Distribución por banda de antigüedad")

    resumen = (
        abiertas.groupby("banda_antiguedad")
        .agg(facturas=("documento", "count"), saldo=("saldo_pendiente", "sum"))
        .reindex(ORDEN_BANDAS)
        .fillna(0)
        .reset_index()
    )

    col_chart, col_tabla = st.columns([2, 1])
    with col_chart:
        chart = (
            alt.Chart(resumen)
            .mark_bar()
            .encode(
                x=alt.X("banda_antiguedad:N", sort=ORDEN_BANDAS, title="Banda"),
                y=alt.Y("saldo:Q", title="Saldo pendiente"),
                tooltip=[
                    alt.Tooltip("banda_antiguedad:N", title="Banda"),
                    alt.Tooltip("saldo:Q", title="Saldo", format="$,.0f"),
                    alt.Tooltip("facturas:Q", title="Facturas"),
                ],
            )
            .properties(height=280)
        )
        st.altair_chart(chart, use_container_width=True)
    with col_tabla:
        resumen_fmt = resumen.copy()
        resumen_fmt["saldo"] = resumen_fmt["saldo"].apply(formato_cop)
        resumen_fmt["facturas"] = resumen_fmt["facturas"].astype(int)
        st.dataframe(
            resumen_fmt.rename(
                columns={
                    "banda_antiguedad": "Banda",
                    "facturas": "# Facturas",
                    "saldo": "Saldo",
                }
            ),
            hide_index=True,
            use_container_width=True,
        )

    st.divider()

    # ---- Tabla filtrable ----
    st.subheader("Detalle de cartera")

    fcol1, fcol2, fcol3, fcol4 = st.columns(4)
    f_cliente = fcol1.selectbox(
        "Cliente", ["Todos"] + sorted(base["cliente"].dropna().unique().tolist())
    )
    f_prioridad = fcol2.selectbox(
        "Prioridad", ["Todas"] + base["prioridad"].unique().tolist()
    )
    f_estado = fcol3.selectbox(
        "Estado", ["Todos"] + base["estado_factura"].unique().tolist()
    )
    f_banda = fcol4.selectbox(
        "Banda",
        ["Todas"] + [b for b in ORDEN_BANDAS if b in base["banda_antiguedad"].values],
    )

    filtrado = base.copy()
    if f_cliente != "Todos":
        filtrado = filtrado[filtrado["cliente"] == f_cliente]
    if f_prioridad != "Todas":
        filtrado = filtrado[filtrado["prioridad"] == f_prioridad]
    if f_estado != "Todos":
        filtrado = filtrado[filtrado["estado_factura"] == f_estado]
    if f_banda != "Todas":
        filtrado = filtrado[filtrado["banda_antiguedad"] == f_banda]

    filtrado = (
        filtrado.assign(_orden=filtrado["prioridad"].map(ORDEN_PRIORIDAD))
        .sort_values(["_orden", "dias_vencido"], ascending=[True, False])
        .drop(columns=["_orden"])
    )

    columnas_mostrar = [
        "cliente",
        "documento",
        "fecha_vencimiento",
        "dias_vencido",
        "saldo_pendiente",
        "banda_antiguedad",
        "estado_factura",
        "prioridad",
        "origen",
    ]
    st.dataframe(
        filtrado[columnas_mostrar].rename(
            columns={
                "cliente": "Cliente",
                "documento": "Documento",
                "fecha_vencimiento": "Vence",
                "dias_vencido": "Días venc.",
                "saldo_pendiente": "Saldo",
                "banda_antiguedad": "Banda",
                "estado_factura": "Estado",
                "prioridad": "Prioridad",
                "origen": "Origen",
            }
        ),
        hide_index=True,
        use_container_width=True,
        column_config={
            "Saldo": st.column_config.NumberColumn(format="$%d"),
            "Vence": st.column_config.DateColumn(format="YYYY-MM-DD"),
        },
    )

    csv_bytes = filtrado[columnas_mostrar].to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Descargar selección (CSV)",
        data=csv_bytes,
        file_name="cartera_filtrada.csv",
        mime="text/csv",
    )


# -----------------------------------------------------------------------------
# Vista 2 — Excepciones por resolver
# -----------------------------------------------------------------------------


def render_excepciones():
    st.title("⚠️ Excepciones por resolver")

    excepciones = cargar_excepciones()
    base = cargar_base()

    if excepciones.empty:
        st.success(
            "🎉 No hay excepciones pendientes. Todos los pagos se asociaron automáticamente."
        )
        return

    st.caption(
        f"Tienes **{len(excepciones)}** caso(s) que el sistema no pudo resolver con confianza. "
        "Tu decisión quedará guardada para que la próxima corrida la aplique automáticamente."
    )

    resumen = excepciones["estado_match"].value_counts().to_dict()
    chips = [
        f"{etiqueta}: {resumen[estado]}"
        for estado, etiqueta in [
            ("AMBIGUO", "⚠️ Ambiguos"),
            ("NO_IDENTIFICADO", "❓ No identificados"),
            ("CLIENTE_DESCONOCIDO", "🆕 Cliente desconocido"),
        ]
        if estado in resumen
    ]
    st.markdown("  ·  ".join(chips))

    # Filtro por origen — permite ocultar casos ya decididos en corridas anteriores.
    if "origen" in excepciones.columns:
        origenes_disponibles = sorted(
            excepciones["origen"].dropna().astype(str).unique().tolist()
        )
        origenes_filtro = st.multiselect(
            "Filtrar por origen",
            options=origenes_disponibles,
            default=origenes_disponibles,
            help="Deselecciona orígenes para ocultar casos. Útil para enfocarte en lo nuevo.",
        )
        excepciones = excepciones[
            excepciones["origen"].astype(str).isin(origenes_filtro)
        ]

    if excepciones.empty:
        st.info("No hay excepciones que coincidan con el filtro.")
        return

    st.divider()

    # Mapa huella → fecha de decisión, para enriquecer tarjetas con origen "Manual".
    fechas_decision = _mapa_huella_a_fecha_decision()

    for idx, exc in excepciones.reset_index(drop=True).iterrows():
        _render_formulario_excepcion(idx, exc, base, fechas_decision)


def _render_formulario_excepcion(
    idx: int,
    exc: pd.Series,
    base: pd.DataFrame,
    fechas_decision: dict[str, str],
):
    estado = exc["estado_match"]
    monto = exc["monto"]
    descripcion = exc["descripcion"]
    cliente = exc.get("cliente_identificado") or "—"
    fecha = pd.Timestamp(exc["fecha"]).strftime("%Y-%m-%d")
    huella = generar_huella_pago(descripcion, monto, exc["fecha"])
    origen = str(exc.get("origen", "")).strip() if "origen" in exc.index else ""

    icono = {"AMBIGUO": "⚠️", "NO_IDENTIFICADO": "❓", "CLIENTE_DESCONOCIDO": "🆕"}.get(
        estado, "🔵"
    )

    with st.container(border=True):
        st.markdown(
            f"### {icono} {estado} — {cliente if cliente != '—' else 'Cliente no identificado'}"
        )

        # Insignia de origen, debajo del título.
        if origen:
            st.markdown(_badge_html(origen), unsafe_allow_html=True)

        # Subtexto contextual: si ya hay decisión registrada para este pago,
        # explicar que reaparece porque el efecto está pendiente fuera del MVP.
        if origen.startswith("Manual") and huella in fechas_decision:
            fecha_dec = fechas_decision[huella][:10]  # solo YYYY-MM-DD
            st.caption(
                f"↳ Ya tomaste una decisión sobre este pago el {fecha_dec}. "
                "Reaparece porque SAP aún debe ajustarlo. "
                "Si quieres anular tu decisión, ve a *Decisiones registradas* y revierte."
            )

        c1, c2, c3 = st.columns(3)
        c1.markdown(f"**Monto:** {formato_cop(monto)}")
        c2.markdown(f"**Fecha:** {fecha}")
        c3.markdown(f"**Huella:** `{huella}`")

        st.markdown(f"**Descripción:** `{descripcion}`")
        st.caption(f"💬 {exc['observacion']}")

        with st.form(key=f"form_excepcion_{idx}_{huella}"):
            if estado == "AMBIGUO":
                accion, datos = _opciones_ambiguo(exc, base)
            elif estado == "NO_IDENTIFICADO":
                accion, datos = _opciones_no_identificado(exc, base)
            elif estado == "CLIENTE_DESCONOCIDO":
                accion, datos = _opciones_cliente_desconocido(exc, base)
            else:
                st.warning(f"Tipo de excepción no soportado: {estado}")
                accion, datos = None, {}

            comentario = st.text_input(
                "Comentario (opcional)",
                key=f"comentario_{idx}",
                placeholder="Ej: Cliente confirmó por WhatsApp, remite adjunto...",
            )

            if st.form_submit_button("💾 Guardar decisión", type="primary") and accion:
                _procesar_decision(
                    huella,
                    int(exc["id_pago"]),
                    float(monto),
                    descripcion,
                    accion,
                    datos,
                    comentario,
                )


def _label_factura(doc: str, base: pd.DataFrame) -> str:
    """Etiqueta enriquecida 'doc · saldo · vence YYYY-MM-DD'."""
    fila = base[base["documento"] == doc]
    if fila.empty:
        return doc
    saldo = fila.iloc[0]["saldo_pendiente"]
    vence = pd.Timestamp(fila.iloc[0]["fecha_vencimiento"]).strftime("%Y-%m-%d")
    return f"{doc}  ·  {formato_cop(saldo)}  ·  vence {vence}"


def _opciones_ambiguo(exc: pd.Series, base: pd.DataFrame):
    """Elegir entre N facturas candidatas, dejar pendiente, o marcar fuera de cartera."""
    candidatas = exc["facturas_asociadas"] or []
    labels = [f"Aplicar a {_label_factura(doc, base)}" for doc in candidatas]
    labels += [
        "Dejar pendiente — investigar con el cliente",
        "No corresponde a cartera",
    ]

    eleccion = st.radio(
        "¿Qué hacer con este pago?", labels, key=f"radio_{exc['id_pago']}"
    )

    if eleccion.startswith("Aplicar a "):
        # Recuperar el documento de la primera columna del label enriquecido
        factura = eleccion.replace("Aplicar a ", "").split("  ·  ")[0].strip()
        return "APLICAR_FACTURA", {
            "factura_asignada": factura,
            "cliente_asignado": exc["cliente_identificado"],
        }
    if eleccion.startswith("Dejar pendiente"):
        return "PENDIENTE", {}
    return "NO_CORRESPONDE", {}


def _opciones_no_identificado(exc: pd.Series, base: pd.DataFrame):
    """Cliente identificado pero sin match: aplicar manualmente, parcial, pendiente o fuera."""
    cliente = exc["cliente_identificado"]
    facturas_cliente = base[
        (base["cliente_norm"].astype(str).str.upper() == str(cliente).upper())
        & (~base["tiene_pago_aplicado"])
    ]

    labels = [
        "Aplicar manualmente a una factura específica",
        "Marcar como pago parcial (dejar pendiente la conciliación)",
        "Dejar pendiente — investigar con el cliente",
        "No corresponde a cartera",
    ]
    eleccion = st.radio(
        "¿Qué hacer con este pago?", labels, key=f"radio_{exc['id_pago']}"
    )
    datos = {"cliente_asignado": cliente}

    if eleccion.startswith("Aplicar manualmente"):
        if facturas_cliente.empty:
            st.warning("Este cliente no tiene facturas abiertas en la cartera actual.")
            return "PENDIENTE", datos

        opciones = {
            _label_factura(row["documento"], base): row["documento"]
            for _, row in facturas_cliente.iterrows()
        }
        escogido = st.selectbox(
            "Selecciona la factura:",
            list(opciones.keys()),
            key=f"sel_{exc['id_pago']}",
        )
        datos["factura_asignada"] = opciones[escogido]
        return "APLICAR_FACTURA", datos

    if eleccion.startswith("Marcar como pago parcial"):
        return "PAGO_PARCIAL", datos
    if eleccion.startswith("Dejar pendiente"):
        return "PENDIENTE", datos
    return "NO_CORRESPONDE", datos


def _opciones_cliente_desconocido(exc: pd.Series, base: pd.DataFrame):
    """Nombre del extracto no resuelve a ningún cliente: aliasar, registrar nuevo, o fuera."""
    labels = [
        "Agregar alias: este nombre corresponde a un cliente existente",
        "Es un cliente nuevo — crear en SAP (queda marcado para gestión externa)",
        "No corresponde a cartera",
    ]
    eleccion = st.radio(
        "¿Qué hacer con este pago?", labels, key=f"radio_{exc['id_pago']}"
    )
    datos = {}

    if eleccion.startswith("Agregar alias"):
        clientes_existentes = sorted(base["cliente"].dropna().unique().tolist())
        cliente_real = st.selectbox(
            "Cliente real (de la cartera):",
            clientes_existentes,
            key=f"sel_cliente_{exc['id_pago']}",
        )
        datos["cliente_asignado"] = cliente_real
        datos["alias_origen"] = str(exc["descripcion"]).strip().upper()
        return "AGREGAR_ALIAS", datos

    if eleccion.startswith("Es un cliente nuevo"):
        return "CLIENTE_NUEVO", datos

    return "NO_CORRESPONDE", datos


def _procesar_decision(huella, id_pago, monto, descripcion, accion, datos, comentario):
    """Persiste la decisión y, si aplica, también el alias en el catálogo."""
    registrar_decision(
        huella_pago=huella,
        id_pago_origen=id_pago,
        monto=monto,
        descripcion_pago=descripcion,
        accion=accion,
        factura_asignada=datos.get("factura_asignada", ""),
        cliente_asignado=datos.get("cliente_asignado", ""),
        alias_origen=datos.get("alias_origen", ""),
        comentario=comentario,
    )

    if accion == "AGREGAR_ALIAS" and datos.get("alias_origen"):
        agregar_alias(
            alias=datos["alias_origen"],
            cliente_real=datos.get("cliente_asignado", ""),
            notas=f"Agregado desde dashboard — {descripcion}",
        )

    st.success(f"✅ Decisión guardada: {accion}")
    st.toast("Decisión registrada. Se aplicará en la próxima corrida.", icon="💾")


# -----------------------------------------------------------------------------
# Vista 3 — Decisiones registradas
# -----------------------------------------------------------------------------


def render_decisiones():
    st.title("📜 Decisiones registradas")
    st.caption(
        "Histórico de las decisiones tomadas por la analista. Revertir una decisión "
        "la marca como REVERTIDA en la auditoría; en la próxima corrida del pipeline "
        "el pago vuelve a la cascada normal."
    )

    df = decisiones_activas_detalle()
    if df.empty:
        st.info("No hay decisiones registradas todavía.")
        return

    c1, _ = st.columns([1, 3])
    c1.metric("📌 Decisiones activas", f"{len(df)}")

    st.divider()

    acciones_disponibles = sorted(df["accion"].dropna().astype(str).unique().tolist())
    accion_filtro = st.multiselect(
        "Filtrar por tipo de acción",
        options=acciones_disponibles,
        default=acciones_disponibles,
    )
    df_vista = df[df["accion"].astype(str).isin(accion_filtro)]

    if df_vista.empty:
        st.info("No hay decisiones que coincidan con el filtro.")
        return

    st.markdown(f"**{len(df_vista)} decisiones**")

    for _, row in df_vista.iterrows():
        _render_tarjeta_decision(row)


def _render_tarjeta_decision(row: pd.Series):
    huella = str(row["huella_pago"])
    accion = str(row.get("accion", ""))
    es_alias = accion.upper() == "AGREGAR_ALIAS"

    # Detalles condicionales: solo aparecen los campos no vacíos.
    monto_fmt = formato_cop(float(row["monto"])) if pd.notna(row.get("monto")) else None
    detalles = [
        _campo("Pago", row.get("descripcion_pago")),
        f"**Monto:** {monto_fmt}" if monto_fmt else None,
        _campo("Cliente", row.get("cliente_asignado")),
        _campo("Factura", row.get("factura_asignada")),
        _campo("Alias origen", row.get("alias_origen")),
        _campo("Comentario", row.get("comentario")),
    ]

    with st.container(border=True):
        top_l, top_r = st.columns([3, 1])

        with top_l:
            st.markdown(f"**{accion}** — `{huella[:10]}...`")
            st.caption(
                f"Registrada el {row.get('fecha_decision', '—')} "
                f"por {row.get('usuario', '—')}"
            )
            for d in detalles:
                if d:
                    st.markdown(d)

        with top_r:
            if es_alias:
                st.caption(
                    "⚙️ Los alias enriquecen el catálogo y no se reversan por esta vía."
                )
            else:
                _render_boton_revertir(huella)


def _render_boton_revertir(huella: str):
    """Botón REVERTIR con confirmación en dos pasos."""
    key_confirm = f"confirm_revert_{huella}"

    if not st.session_state.get(key_confirm, False):
        if st.button(
            "↩️ Revertir", key=f"ask_revert_{huella}", use_container_width=True
        ):
            st.session_state[key_confirm] = True
            st.rerun()
        return

    motivo = st.text_input(
        "Motivo (opcional)",
        key=f"motivo_revert_{huella}",
        placeholder="ej. asigné factura equivocada",
    )
    c1, c2 = st.columns(2)

    if c1.button("✅ Confirmar", key=f"do_revert_{huella}", use_container_width=True):
        ok = revertir_decision(
            huella_pago=huella, motivo=motivo or "", usuario="analista"
        )
        st.toast(
            "Decisión revertida." if ok else "No se pudo revertir.",
            icon="↩️" if ok else "⚠️",
        )
        st.session_state[key_confirm] = False
        st.cache_data.clear()
        st.rerun()

    if c2.button("Cancelar", key=f"cancel_revert_{huella}", use_container_width=True):
        st.session_state[key_confirm] = False
        st.rerun()


# -----------------------------------------------------------------------------
# Vista 4 — Generar correos de seguimiento
# -----------------------------------------------------------------------------


def render_generar_correos():
    st.title("📧 Generar correos de seguimiento")
    st.caption(
        "Selecciona un cliente para generar el correo correspondiente según su "
        "etapa de gestión. La analista decide qué correos efectivamente envía; "
        "esta vista solo prepara el contenido para copiar y pegar."
    )

    base = cargar_base()
    if base.empty:
        st.warning("No hay base consolidada. Ejecuta el pipeline primero.")
        return

    clientes = _clientes_con_cartera_abierta(base)
    if clientes.empty:
        st.success(
            "🎉 No hay clientes con cartera abierta. No hay correos que generar."
        )
        return

    # Selector de cliente — ordenado por urgencia (más vencido arriba).
    opciones = clientes["cliente"].tolist()
    cliente_sel = st.selectbox(
        f"Cliente ({len(opciones)} con cartera abierta, ordenados por urgencia):",
        opciones,
    )

    fila = clientes[clientes["cliente"] == cliente_sel].iloc[0]

    # Mini-resumen del cliente seleccionado.
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📄 Facturas abiertas", f"{int(fila['n_facturas'])}")
    c2.metric("💰 Saldo pendiente", formato_cop(fila["saldo_total"]))
    c3.metric("📅 Días máx. vencido", f"{int(fila['dias_max_vencido'])}")
    c4.metric("🎯 Banda más vencida", fila["banda_mas_vencida"])

    # Construir el correo a partir de las facturas abiertas del cliente.
    facturas_cliente = base[
        (base["cliente"] == cliente_sel) & (~base["tiene_pago_aplicado"])
    ]
    correo = construir_correo(cliente_sel, facturas_cliente)

    st.info(f"**Etapa de gestión:** {correo['etiqueta_etapa']}")

    st.divider()

    # Pestañas: editar y copiar.
    # La separación permite usar st.code en "Copiar" con su botón nativo de
    # copia al portapapeles, sin el overhead de simular esa funcionalidad
    # sobre un text_area editable.
    tab_editar, tab_copiar = st.tabs(["✏️ Editar", "📋 Copiar"])

    with tab_editar:
        asunto_editado = st.text_input(
            "Asunto",
            value=correo["asunto"],
            key=f"asunto_{cliente_sel}",
        )
        cuerpo_editado = st.text_area(
            "Cuerpo del correo",
            value=correo["cuerpo"],
            height=420,
            key=f"cuerpo_{cliente_sel}",
            help=(
                "Edita libremente antes de copiar. La tabla está en formato "
                "Markdown — Gmail y Outlook web la renderizan al pegar."
            ),
        )

    with tab_copiar:
        st.caption(
            "Cada bloque tiene un botón de copia (esquina superior derecha). "
            "Pega primero el asunto en tu cliente de correo, luego el cuerpo."
        )
        st.markdown("**Asunto:**")
        st.code(asunto_editado, language=None)
        st.markdown("**Cuerpo:**")
        st.code(cuerpo_editado, language=None)


# -----------------------------------------------------------------------------
# Router
# -----------------------------------------------------------------------------

if vista.startswith("📊"):
    render_estado_cartera()
elif vista.startswith("⚠️"):
    render_excepciones()
elif vista.startswith("📧"):
    render_generar_correos()
else:
    render_decisiones()
