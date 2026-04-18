"""
Dashboard de Gestión de Cartera — +logística

Etapa A del Paso 6:
    - Vista 1: Estado de cartera (KPIs, distribución, tabla filtrable).
    - Vista 2: Excepciones por resolver (formularios que persisten decisiones).

Ejecutar desde la raíz del proyecto:
    streamlit run app/streamlit_app.py
"""

import os
import sys
from ast import literal_eval
from pathlib import Path

# Hacer importables los módulos de src/ y ubicarnos en la raíz del proyecto
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

import pandas as pd
import streamlit as st

from registro_decisiones import (
    agregar_alias,
    cargar_decisiones,
    generar_huella_pago,
    registrar_decision,
)

# -----------------------------------------------------------------------------
# Configuración general de la página
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Cartera +logística",
    page_icon="💼",
    layout="wide",
)

RUTA_BASE = "data/output/base_consolidada.csv"
RUTA_EXCEPCIONES = "data/output/excepciones.csv"


# -----------------------------------------------------------------------------
# Utilidades de carga con caché
# -----------------------------------------------------------------------------
@st.cache_data
def cargar_base(ruta: str = RUTA_BASE) -> pd.DataFrame:
    """Carga la base consolidada. La caché se invalida al tocar el botón Recargar."""
    if not Path(ruta).exists():
        return pd.DataFrame()
    df = pd.read_csv(ruta, parse_dates=["fecha_vencimiento", "fecha_contabilizacion", "fecha_pago"])
    return df


@st.cache_data
def cargar_excepciones(ruta: str = RUTA_EXCEPCIONES) -> pd.DataFrame:
    """Carga las excepciones. Parsea la columna facturas_asociadas que viene como string."""
    if not Path(ruta).exists():
        return pd.DataFrame()
    df = pd.read_csv(ruta, parse_dates=["fecha"])
    # facturas_asociadas viene como string "['FV-1040', 'FV-1041']" → la convertimos a lista real
    if "facturas_asociadas" in df.columns:
        df["facturas_asociadas"] = df["facturas_asociadas"].apply(_parsear_lista_segura)
    return df


def _parsear_lista_segura(valor):
    """Convierte un string tipo "['A', 'B']" a lista real. Tolerante a NaN y vacíos."""
    if pd.isna(valor) or valor == "" or valor == "[]":
        return []
    try:
        res = literal_eval(valor)
        return list(res) if isinstance(res, (list, tuple)) else []
    except (ValueError, SyntaxError):
        return []


def formato_cop(valor) -> str:
    """Formatea un número como moneda colombiana."""
    try:
        return f"${valor:,.0f}"
    except (TypeError, ValueError):
        return "—"


# -----------------------------------------------------------------------------
# SIDEBAR (navegación + acciones globales)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 💼 Cartera +logística")
    st.caption("MVP — Reto 10 · Beca SER ANDI")

    vista = st.radio(
        "Vista",
        ["📊 Estado de cartera", "⚠️ Excepciones por resolver"],
        label_visibility="collapsed",
    )

    st.divider()

    # Botón para invalidar caché y recargar los CSVs de output/
    if st.button("🔄 Recargar datos", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()

    # Info de contexto
    base_existe = Path(RUTA_BASE).exists()
    if base_existe:
        mtime = Path(RUTA_BASE).stat().st_mtime
        ts = pd.Timestamp.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        st.caption(f"**Última actualización:**\n\n{ts}")
    else:
        st.warning("Aún no hay datos. Corre `python run_pipeline.py` primero.")

    # Contador de decisiones ya registradas (Etapa B — trazabilidad)
    try:
        df_dec = cargar_decisiones()
        if not df_dec.empty:
            st.caption(
                f"📝 **Decisiones registradas:** {len(df_dec)}\n\n"
                f"_Se aplicarán en la próxima corrida del pipeline._"
            )
    except Exception:
        pass


# -----------------------------------------------------------------------------
# VISTA 1 — Estado de cartera
# -----------------------------------------------------------------------------
def render_estado_cartera():
    st.title("📊 Estado de cartera")

    base = cargar_base()
    if base.empty:
        st.warning("No hay base consolidada. Ejecuta el pipeline primero.")
        return

    # ---------- Fila de KPIs ----------
    col1, col2, col3, col4 = st.columns(4)

    saldo_total = base.loc[~base["tiene_pago_aplicado"], "saldo_pendiente"].sum()
    facturas_abiertas = (~base["tiene_pago_aplicado"]).sum()
    criticas = base[(base["prioridad"] == "CRITICO") & (~base["tiene_pago_aplicado"])]
    saldo_critico = criticas["saldo_pendiente"].sum()
    pagos_aplicados = base["tiene_pago_aplicado"].sum()

    col1.metric("💰 Saldo pendiente", formato_cop(saldo_total))
    col2.metric("📄 Facturas abiertas", f"{facturas_abiertas}")
    col3.metric(
        "🔴 Cartera crítica",
        formato_cop(saldo_critico),
        delta=f"{len(criticas)} facturas" if len(criticas) else "sin casos",
        delta_color="inverse",
    )
    col4.metric("✅ Pagos aplicados", f"{pagos_aplicados}")

    st.divider()

    # ---------- Distribución por banda de antigüedad ----------
    st.subheader("Distribución por banda de antigüedad")

    orden_bandas = ["AL_DIA", "0-30", "31-60", "61-90", "91-120", "121+"]
    abiertas = base[~base["tiene_pago_aplicado"]]
    resumen = (
        abiertas.groupby("banda_antiguedad")
        .agg(facturas=("documento", "count"), saldo=("saldo_pendiente", "sum"))
        .reindex(orden_bandas)
        .fillna(0)
        .reset_index()
    )

    col_chart, col_tabla = st.columns([2, 1])
    with col_chart:
        st.bar_chart(resumen.set_index("banda_antiguedad")["saldo"], height=280)
    with col_tabla:
        resumen_fmt = resumen.copy()
        resumen_fmt["saldo"] = resumen_fmt["saldo"].apply(formato_cop)
        resumen_fmt["facturas"] = resumen_fmt["facturas"].astype(int)
        st.dataframe(
            resumen_fmt.rename(columns={
                "banda_antiguedad": "Banda",
                "facturas": "# Facturas",
                "saldo": "Saldo",
            }),
            hide_index=True,
            use_container_width=True,
        )

    st.divider()

    # ---------- Tabla de cartera con filtros ----------
    st.subheader("Detalle de cartera")

    fcol1, fcol2, fcol3, fcol4 = st.columns(4)
    clientes = ["Todos"] + sorted(base["cliente"].dropna().unique().tolist())
    prioridades = ["Todas"] + base["prioridad"].unique().tolist()
    estados = ["Todos"] + base["estado_factura"].unique().tolist()
    bandas = ["Todas"] + [b for b in orden_bandas if b in base["banda_antiguedad"].values]

    f_cliente = fcol1.selectbox("Cliente", clientes)
    f_prioridad = fcol2.selectbox("Prioridad", prioridades)
    f_estado = fcol3.selectbox("Estado", estados)
    f_banda = fcol4.selectbox("Banda", bandas)

    filtrado = base.copy()
    if f_cliente != "Todos":
        filtrado = filtrado[filtrado["cliente"] == f_cliente]
    if f_prioridad != "Todas":
        filtrado = filtrado[filtrado["prioridad"] == f_prioridad]
    if f_estado != "Todos":
        filtrado = filtrado[filtrado["estado_factura"] == f_estado]
    if f_banda != "Todas":
        filtrado = filtrado[filtrado["banda_antiguedad"] == f_banda]

    # Ordenar por prioridad crítica primero
    orden_prioridad = {"CRITICO": 0, "ALTO": 1, "MEDIO": 2, "BAJO": 3, "RESUELTO": 4}
    filtrado = filtrado.assign(
        _orden=filtrado["prioridad"].map(orden_prioridad)
    ).sort_values(["_orden", "dias_vencido"], ascending=[True, False]).drop(columns=["_orden"])

    columnas_mostrar = [
        "cliente", "documento", "fecha_vencimiento", "dias_vencido",
        "saldo_pendiente", "banda_antiguedad", "estado_factura",
        "prioridad", "metodo_match",
    ]
    st.dataframe(
        filtrado[columnas_mostrar].rename(columns={
            "cliente": "Cliente",
            "documento": "Documento",
            "fecha_vencimiento": "Vence",
            "dias_vencido": "Días venc.",
            "saldo_pendiente": "Saldo",
            "banda_antiguedad": "Banda",
            "estado_factura": "Estado",
            "prioridad": "Prioridad",
            "metodo_match": "Método match",
        }),
        hide_index=True,
        use_container_width=True,
        column_config={
            "Saldo": st.column_config.NumberColumn(format="$%d"),
            "Vence": st.column_config.DateColumn(format="YYYY-MM-DD"),
        },
    )

    # Descarga
    csv_bytes = filtrado[columnas_mostrar].to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Descargar selección (CSV)",
        data=csv_bytes,
        file_name="cartera_filtrada.csv",
        mime="text/csv",
    )


# -----------------------------------------------------------------------------
# VISTA 2 — Excepciones por resolver
# -----------------------------------------------------------------------------
def render_excepciones():
    st.title("⚠️ Excepciones por resolver")

    excepciones = cargar_excepciones()
    base = cargar_base()

    if excepciones.empty:
        st.success("🎉 No hay excepciones pendientes. Todos los pagos se asociaron automáticamente.")
        return

    st.caption(
        f"Tienes **{len(excepciones)}** caso(s) que el sistema no pudo resolver con confianza. "
        "Revísalos y registra la decisión. Tu decisión quedará guardada para "
        "que la próxima corrida del pipeline la aplique automáticamente."
    )

    # Resumen por tipo
    resumen = excepciones["estado_match"].value_counts().to_dict()
    chips = []
    if "AMBIGUO" in resumen:
        chips.append(f"⚠️ Ambiguos: {resumen['AMBIGUO']}")
    if "NO_IDENTIFICADO" in resumen:
        chips.append(f"❓ No identificados: {resumen['NO_IDENTIFICADO']}")
    if "CLIENTE_DESCONOCIDO" in resumen:
        chips.append(f"🆕 Cliente desconocido: {resumen['CLIENTE_DESCONOCIDO']}")
    st.markdown("  ·  ".join(chips))

    st.divider()

    # Un formulario por excepción
    for idx, exc in excepciones.reset_index(drop=True).iterrows():
        _render_formulario_excepcion(idx, exc, base)


def _render_formulario_excepcion(idx: int, exc: pd.Series, base: pd.DataFrame):
    """Renderiza un formulario para una excepción particular."""
    estado = exc["estado_match"]
    monto = exc["monto"]
    descripcion = exc["descripcion"]
    cliente = exc.get("cliente_identificado") or "—"
    fecha = pd.Timestamp(exc["fecha"]).strftime("%Y-%m-%d")
    huella = generar_huella_pago(descripcion, monto, exc["fecha"])

    # Color/ícono por tipo de estado
    icono = {
        "AMBIGUO": "⚠️",
        "NO_IDENTIFICADO": "❓",
        "CLIENTE_DESCONOCIDO": "🆕",
    }.get(estado, "🔵")

    with st.container(border=True):
        # Encabezado
        st.markdown(f"### {icono} {estado} — {cliente if cliente != '—' else 'Cliente no identificado'}")

        col1, col2, col3 = st.columns(3)
        col1.markdown(f"**Monto:** {formato_cop(monto)}")
        col2.markdown(f"**Fecha:** {fecha}")
        col3.markdown(f"**Huella:** `{huella}`")

        st.markdown(f"**Descripción:** `{descripcion}`")
        st.caption(f"💬 {exc['observacion']}")

        # Formulario con opciones específicas al estado
        with st.form(key=f"form_excepcion_{idx}_{huella}"):
            if estado == "AMBIGUO":
                accion_elegida, datos_extra = _opciones_ambiguo(exc, base)
            elif estado == "NO_IDENTIFICADO":
                accion_elegida, datos_extra = _opciones_no_identificado(exc, base)
            elif estado == "CLIENTE_DESCONOCIDO":
                accion_elegida, datos_extra = _opciones_cliente_desconocido(exc, base)
            else:
                st.warning(f"Tipo de excepción no soportado: {estado}")
                accion_elegida, datos_extra = None, {}

            comentario = st.text_input(
                "Comentario (opcional)",
                key=f"comentario_{idx}",
                placeholder="Ej: Cliente confirmó por WhatsApp, remite adjunto...",
            )

            submitted = st.form_submit_button(
                "💾 Guardar decisión",
                use_container_width=False,
                type="primary",
            )

            if submitted and accion_elegida:
                _procesar_decision(
                    huella=huella,
                    id_pago=int(exc["id_pago"]),
                    monto=float(monto),
                    descripcion=descripcion,
                    accion=accion_elegida,
                    datos_extra=datos_extra,
                    comentario=comentario,
                )


def _opciones_ambiguo(exc: pd.Series, base: pd.DataFrame):
    """Opciones para un caso AMBIGUO: múltiples facturas candidatas."""
    facturas_candidatas = exc["facturas_asociadas"] or []

    # Enriquecer con info de cada candidata
    labels = []
    for doc in facturas_candidatas:
        fila = base[base["documento"] == doc]
        if not fila.empty:
            saldo = fila.iloc[0]["saldo_pendiente"]
            vence = pd.Timestamp(fila.iloc[0]["fecha_vencimiento"]).strftime("%Y-%m-%d")
            labels.append(f"Aplicar a {doc}  ·  {formato_cop(saldo)}  ·  vence {vence}")
        else:
            labels.append(f"Aplicar a {doc}")
    labels.append("Dejar pendiente — investigar con el cliente")
    labels.append("No corresponde a cartera")

    eleccion = st.radio("¿Qué hacer con este pago?", labels, key=f"radio_{exc['id_pago']}")

    if eleccion.startswith("Aplicar a "):
        factura = eleccion.split("  ·  ")[0].replace("Aplicar a ", "").strip()
        return "APLICAR_FACTURA", {"factura_asignada": factura, "cliente_asignado": exc["cliente_identificado"]}
    if eleccion.startswith("Dejar pendiente"):
        return "PENDIENTE", {}
    return "NO_CORRESPONDE", {}


def _opciones_no_identificado(exc: pd.Series, base: pd.DataFrame):
    """Opciones para NO_IDENTIFICADO: el cliente existe pero ningún match."""
    cliente = exc["cliente_identificado"]
    facturas_cliente = base[
        (base["cliente_norm"].astype(str).str.upper() == str(cliente).upper())
        & (~base["tiene_pago_aplicado"])
    ]

    labels_base = [
        "Aplicar manualmente a una factura específica",
        "Marcar como pago parcial (dejar pendiente la conciliación)",
        "Dejar pendiente — investigar con el cliente",
        "No corresponde a cartera",
    ]
    eleccion = st.radio("¿Qué hacer con este pago?", labels_base, key=f"radio_{exc['id_pago']}")

    datos = {"cliente_asignado": cliente}

    if eleccion.startswith("Aplicar manualmente"):
        if facturas_cliente.empty:
            st.warning("Este cliente no tiene facturas abiertas en la cartera actual.")
            return "PENDIENTE", datos
        opciones_doc = {
            f"{row['documento']}  ·  {formato_cop(row['saldo_pendiente'])}  ·  vence {pd.Timestamp(row['fecha_vencimiento']).strftime('%Y-%m-%d')}": row["documento"]
            for _, row in facturas_cliente.iterrows()
        }
        escogido = st.selectbox("Selecciona la factura:", list(opciones_doc.keys()), key=f"sel_{exc['id_pago']}")
        datos["factura_asignada"] = opciones_doc[escogido]
        return "APLICAR_FACTURA", datos

    if eleccion.startswith("Marcar como pago parcial"):
        return "PAGO_PARCIAL", datos
    if eleccion.startswith("Dejar pendiente"):
        return "PENDIENTE", datos
    return "NO_CORRESPONDE", datos


def _opciones_cliente_desconocido(exc: pd.Series, base: pd.DataFrame):
    """Opciones para CLIENTE_DESCONOCIDO: nombre del extracto no resuelve a ningún cliente."""
    labels = [
        "Agregar alias: este nombre corresponde a un cliente existente",
        "Es un cliente nuevo — crear en SAP (queda marcado para gestión externa)",
        "No corresponde a cartera",
    ]
    eleccion = st.radio("¿Qué hacer con este pago?", labels, key=f"radio_{exc['id_pago']}")

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


def _procesar_decision(
    huella: str,
    id_pago: int,
    monto: float,
    descripcion: str,
    accion: str,
    datos_extra: dict,
    comentario: str,
):
    """Registra la decisión en el CSV y actualiza alias si aplica."""
    registrar_decision(
        huella_pago=huella,
        id_pago_origen=id_pago,
        monto=monto,
        descripcion_pago=descripcion,
        accion=accion,
        factura_asignada=datos_extra.get("factura_asignada", ""),
        cliente_asignado=datos_extra.get("cliente_asignado", ""),
        alias_origen=datos_extra.get("alias_origen", ""),
        comentario=comentario,
    )

    # Si la decisión fue agregar alias, también lo guardamos en el catálogo de alias
    if accion == "AGREGAR_ALIAS" and datos_extra.get("alias_origen"):
        agregar_alias(
            alias=datos_extra["alias_origen"],
            cliente_real=datos_extra.get("cliente_asignado", ""),
            notas=f"Agregado desde dashboard — {descripcion}",
        )

    st.success(f"✅ Decisión guardada: {accion}")
    st.toast("Decisión registrada. Se aplicará en la próxima corrida del pipeline.", icon="💾")


# -----------------------------------------------------------------------------
# Router principal
# -----------------------------------------------------------------------------
if vista.startswith("📊"):
    render_estado_cartera()
else:
    render_excepciones()
