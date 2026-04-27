"""
Registro de decisiones de la analista.

Cuando la analista resuelve una excepción (AMBIGUO / NO_IDENTIFICADO /
CLIENTE_DESCONOCIDO) en el dashboard, su decisión se guarda aquí para
que en la siguiente corrida del pipeline se aplique automáticamente.

Archivo destino: data/output/decisiones_analista.csv

Cada pago se identifica por una "huella" estable (hash de descripción +
monto + fecha), no por el id_pago posicional que cambia entre corridas.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pandas as pd


RUTA_DECISIONES = Path("data/output/decisiones_analista.csv")
RUTA_HISTORIAL = Path("data/output/historial_pagos.csv")

# Columnas del registro de decisiones (contrato fijo)
COLUMNAS = [
    "fecha_decision",
    "huella_pago",
    "id_pago_origen",
    "monto",
    "descripcion_pago",
    "accion",  # APLICAR_FACTURA | PENDIENTE | NO_CORRESPONDE | AGREGAR_ALIAS | CLIENTE_NUEVO
    "factura_asignada",  # documento de la factura a la que se aplicó (o vacío)
    "cliente_asignado",  # cliente final (útil sobre todo para AGREGAR_ALIAS)
    "alias_origen",  # para AGREGAR_ALIAS: el texto que aparece en el extracto
    "comentario",
    "usuario",
]

# Columnas del historial de pagos procesados (contrato fijo).
# Solo entran pagos resueltos con confianza (estado ASOCIADO).
COLUMNAS_HISTORIAL = [
    "fecha_corrida",  # timestamp de cuándo se procesó este pago
    "huella_pago",  # identificador estable del pago
    "fecha_pago",  # fecha real del pago según el extracto
    "monto",
    "descripcion_pago",
    "estado_match_inicial",  # cómo lo resolvió el matcher (ASOCIADO siempre, por contrato)
    "metodo_match",  # exacto | acumulado | referencia | decision_analista
    "facturas_asociadas",  # lista de documentos a los que se aplicó (string)
]


def generar_huella_pago(descripcion: str, monto: float, fecha) -> str:
    """
    Genera una huella estable para un pago.

    La idea: un mismo pago (misma descripción, mismo monto, misma fecha)
    siempre produce la misma huella, sin importar su posición en el
    DataFrame. Así podemos reconocerlo entre corridas distintas.
    """
    desc = str(descripcion).strip().upper()
    monto_str = f"{float(monto):.2f}"
    fecha_str = pd.Timestamp(fecha).strftime("%Y-%m-%d")
    base = f"{desc}|{monto_str}|{fecha_str}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def _asegurar_archivo_existe(ruta: Path = RUTA_DECISIONES) -> None:
    """Crea el CSV con encabezados si no existe."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if not ruta.exists():
        pd.DataFrame(columns=COLUMNAS).to_csv(ruta, index=False)


def registrar_decision(
    huella_pago: str,
    id_pago_origen: int,
    monto: float,
    descripcion_pago: str,
    accion: str,
    factura_asignada: str = "",
    cliente_asignado: str = "",
    alias_origen: str = "",
    comentario: str = "",
    usuario: str = "analista",
    ruta: Path = RUTA_DECISIONES,
) -> None:
    """Añade una fila al registro de decisiones."""
    _asegurar_archivo_existe(ruta)

    nueva_fila = {
        "fecha_decision": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "huella_pago": huella_pago,
        "id_pago_origen": id_pago_origen,
        "monto": monto,
        "descripcion_pago": descripcion_pago,
        "accion": accion,
        "factura_asignada": factura_asignada,
        "cliente_asignado": cliente_asignado,
        "alias_origen": alias_origen,
        "comentario": comentario,
        "usuario": usuario,
    }
    df = pd.read_csv(ruta)
    df = pd.concat([df, pd.DataFrame([nueva_fila])], ignore_index=True)
    df.to_csv(ruta, index=False)


def cargar_decisiones(ruta: Path = RUTA_DECISIONES) -> pd.DataFrame:
    """Carga el historial de decisiones. Si no existe, retorna DataFrame vacío."""
    if not Path(ruta).exists():
        return pd.DataFrame(columns=COLUMNAS)
    return pd.read_csv(ruta)


def ya_tiene_decision(huella_pago: str, ruta: Path = RUTA_DECISIONES) -> dict | None:
    """
    Retorna la última decisión para esta huella, o None si no hay.
    (Se usará en la Etapa B, cuando el matcher consulte decisiones previas.)
    """
    df = cargar_decisiones(ruta)
    if df.empty:
        return None
    match = df[df["huella_pago"] == huella_pago]
    if match.empty:
        return None
    return match.iloc[-1].to_dict()


def decisiones_por_huella(ruta: Path = RUTA_DECISIONES) -> dict[str, dict]:
    """
    Retorna un dict {huella_pago: ultima_decision_como_dict}.

    A diferencia de ya_tiene_decision (que consulta una huella a la vez),
    esta función carga el archivo una sola vez y retorna un índice completo,
    pensado para que el matcher haga lookup O(1) por cada pago durante la
    cascada — sin tener que reabrir el CSV en cada iteración.

    Si una huella tiene múltiples decisiones registradas (porque la analista
    cambió de opinión entre corridas), se conserva la más reciente.
    """
    df = cargar_decisiones(ruta)
    if df.empty:
        return {}
    # drop_duplicates conservando la última preserva la decisión más reciente
    # por huella (el archivo está ordenado cronológicamente por construcción).
    df = df.drop_duplicates(subset=["huella_pago"], keep="last")
    return {str(row["huella_pago"]): row.to_dict() for _, row in df.iterrows()}


def agregar_alias(
    alias: str,
    cliente_real: str,
    notas: str = "",
    ruta: Path = Path("data/reference/alias_clientes.csv"),
) -> None:
    """
    Añade un alias al catálogo. Si ya existe (mismo alias), no lo duplica.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)

    # Si no existe, creamos con encabezados
    if not ruta.exists():
        pd.DataFrame(columns=["alias", "cliente_real", "notas"]).to_csv(
            ruta, index=False
        )

    df = pd.read_csv(ruta, comment="#")
    alias_norm = str(alias).strip().upper()

    # ¿Ya existe?
    if (
        "alias" in df.columns
        and alias_norm in df["alias"].astype(str).str.upper().values
    ):
        return  # no duplicar

    nueva = pd.DataFrame(
        [
            {
                "alias": alias_norm,
                "cliente_real": str(cliente_real).strip().upper(),
                "notas": notas,
            }
        ]
    )
    df_out = pd.concat([df, nueva], ignore_index=True)
    df_out.to_csv(ruta, index=False)


# =============================================================================
# Historial de pagos procesados
# =============================================================================
# Memoria del sistema: cada pago resuelto con confianza (estado ASOCIADO) en
# una corrida queda registrado aquí. En la siguiente corrida, el matcher
# consulta este historial para evitar reprocesar pagos que SAP ya aplicó.
#
# Las excepciones NO entran al historial hasta que la analista decida sobre
# ellas — por eso este archivo es complementario a decisiones_analista.csv,
# no redundante.
# =============================================================================


def _asegurar_historial_existe(ruta: Path = RUTA_HISTORIAL) -> None:
    """Crea el CSV del historial con encabezados si no existe."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if not ruta.exists():
        pd.DataFrame(columns=COLUMNAS_HISTORIAL).to_csv(ruta, index=False)


def registrar_pago_procesado(
    huella_pago: str,
    fecha_pago,
    monto: float,
    descripcion_pago: str,
    estado_match_inicial: str,
    metodo_match: str,
    facturas_asociadas: list[str] | str = "",
    fecha_corrida: str | None = None,
    ruta: Path = RUTA_HISTORIAL,
) -> None:
    """
    Añade una fila al historial de pagos procesados.

    Solo debe llamarse para pagos con estado ASOCIADO (resueltos con confianza).
    Si por error llega otro estado, igual se registra — la responsabilidad de
    filtrar está en quien orquesta (run_pipeline.py).

    Parámetros:
        huella_pago: identificador estable (sha1 truncado) del pago.
        fecha_pago: fecha del movimiento bancario.
        monto: valor del pago.
        descripcion_pago: descripción tal como vino del extracto.
        estado_match_inicial: típicamente "ASOCIADO".
        metodo_match: cómo se resolvió (exacto, acumulado, referencia, ...).
        facturas_asociadas: lista de documentos o string serializable.
        fecha_corrida: timestamp de la corrida. Si es None, se usa "ahora".
    """
    _asegurar_historial_existe(ruta)

    if fecha_corrida is None:
        fecha_corrida = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Normalizar facturas_asociadas a string para que el CSV sea estable
    if isinstance(facturas_asociadas, list):
        facturas_str = str(facturas_asociadas)
    else:
        facturas_str = str(facturas_asociadas) if facturas_asociadas else ""

    nueva_fila = {
        "fecha_corrida": fecha_corrida,
        "huella_pago": huella_pago,
        "fecha_pago": pd.Timestamp(fecha_pago).strftime("%Y-%m-%d"),
        "monto": float(monto),
        "descripcion_pago": str(descripcion_pago),
        "estado_match_inicial": estado_match_inicial,
        "metodo_match": metodo_match,
        "facturas_asociadas": facturas_str,
    }

    df = pd.read_csv(ruta)
    df = pd.concat([df, pd.DataFrame([nueva_fila])], ignore_index=True)
    df.to_csv(ruta, index=False)


def cargar_historial_pagos(ruta: Path = RUTA_HISTORIAL) -> pd.DataFrame:
    """
    Carga el historial completo de pagos procesados.

    Útil para auditoría, reportes o para mostrar la bitácora en el dashboard.
    Si no existe, retorna un DataFrame vacío con el esquema correcto.
    """
    if not Path(ruta).exists():
        return pd.DataFrame(columns=COLUMNAS_HISTORIAL)
    return pd.read_csv(ruta)


def huellas_ya_procesadas(ruta: Path = RUTA_HISTORIAL) -> set[str]:
    """
    Retorna el conjunto de huellas que ya fueron procesadas en corridas previas.

    Esta es la función que consulta el matcher antes de correr la cascada:
    si la huella del pago actual está en este set, el pago se marca como
    YA_PROCESADO y no entra al flujo de matching ni al de excepciones.

    Devolver un set (no una lista) garantiza lookup O(1) — importante cuando
    el historial crezca con meses de uso.
    """
    if not Path(ruta).exists():
        return set()
    df = pd.read_csv(ruta, usecols=["huella_pago"])
    return set(df["huella_pago"].astype(str).tolist())
