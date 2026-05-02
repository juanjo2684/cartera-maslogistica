"""Registro de decisiones de la analista e historial de pagos procesados.

Las decisiones (decisiones_analista.csv) son el "aprendizaje" del sistema:
cuando la analista resuelve una excepción, su decisión se reaplicará en
corridas siguientes para el mismo pago, identificado por una huella estable.

El historial (historial_pagos.csv) es el "blindaje contra duplicidad":
los pagos ya resueltos con confianza no vuelven a entrar al matching.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pandas as pd

RUTA_DECISIONES = Path("data/output/decisiones_analista.csv")
RUTA_HISTORIAL = Path("data/output/historial_pagos.csv")

COLUMNAS = [
    "fecha_decision",
    "huella_pago",
    "id_pago_origen",
    "monto",
    "descripcion_pago",
    "accion",  # APLICAR_FACTURA | PAGO_PARCIAL | PENDIENTE | NO_CORRESPONDE | AGREGAR_ALIAS | CLIENTE_NUEVO | REVERTIR
    "factura_asignada",
    "cliente_asignado",
    "alias_origen",  # texto del extracto (solo para AGREGAR_ALIAS)
    "comentario",
    "usuario",
    "estado_decision",  # ACTIVA | REVERTIDA
]

COLUMNAS_HISTORIAL = [
    "fecha_corrida",
    "huella_pago",
    "fecha_pago",
    "monto",
    "descripcion_pago",
    "estado_match_inicial",
    "metodo_match",
    "facturas_asociadas",
]


# -----------------------------------------------------------------------------
# Decisiones de la analista
# -----------------------------------------------------------------------------


def generar_huella_pago(descripcion: str, monto: float, fecha) -> str:
    """Hash estable que identifica un pago entre corridas."""
    desc = str(descripcion).strip().upper()
    monto_str = f"{float(monto):.2f}"
    fecha_str = pd.Timestamp(fecha).strftime("%Y-%m-%d")
    base = f"{desc}|{monto_str}|{fecha_str}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def _asegurar_archivo_existe(ruta: Path = RUTA_DECISIONES) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if not ruta.exists():
        pd.DataFrame(columns=COLUMNAS).to_csv(ruta, index=False)


def _asegurar_columna_estado(df: pd.DataFrame) -> pd.DataFrame:
    """Compatibilidad con CSVs anteriores a la columna estado_decision."""
    if "estado_decision" not in df.columns:
        df = df.copy()
        df["estado_decision"] = "ACTIVA"
    return df


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
    estado_decision: str = "ACTIVA",
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
        "estado_decision": estado_decision,
    }
    df = _asegurar_columna_estado(pd.read_csv(ruta))
    df = pd.concat([df, pd.DataFrame([nueva_fila])], ignore_index=True)
    df.to_csv(ruta, index=False)


def cargar_decisiones(ruta: Path = RUTA_DECISIONES) -> pd.DataFrame:
    if not Path(ruta).exists():
        return pd.DataFrame(columns=COLUMNAS)
    return pd.read_csv(ruta)


def ya_tiene_decision(huella_pago: str, ruta: Path = RUTA_DECISIONES) -> dict | None:
    """Última decisión registrada para una huella, o None."""
    df = cargar_decisiones(ruta)
    if df.empty:
        return None
    match = df[df["huella_pago"] == huella_pago]
    return match.iloc[-1].to_dict() if not match.empty else None


def decisiones_por_huella(ruta: Path = RUTA_DECISIONES) -> dict[str, dict]:
    """Índice {huella: última_decisión_ACTIVA}. Lo consume el matcher."""
    df = cargar_decisiones(ruta)
    if df.empty:
        return {}

    df = _asegurar_columna_estado(df)
    df = df.drop_duplicates(subset=["huella_pago"], keep="last")
    df = df[df["estado_decision"].astype(str).str.upper() == "ACTIVA"]
    return {str(row["huella_pago"]): row.to_dict() for _, row in df.iterrows()}


def revertir_decision(
    huella_pago: str,
    motivo: str = "",
    usuario: str = "analista",
    ruta: Path = RUTA_DECISIONES,
) -> bool:
    """Marca como REVERTIDA la última decisión activa de una huella.

    No borra: añade una nueva fila REVERTIR/REVERTIDA preservando los datos
    originales. Los AGREGAR_ALIAS no se reversan por esta vía.
    """
    df = cargar_decisiones(ruta)
    if df.empty:
        return False

    df = _asegurar_columna_estado(df)
    candidatas = df[df["huella_pago"].astype(str) == str(huella_pago)]
    if candidatas.empty:
        return False

    ultima = candidatas.iloc[-1]
    estado = str(ultima.get("estado_decision", "ACTIVA")).upper()
    accion = str(ultima.get("accion", "")).upper()

    if estado != "ACTIVA" or accion == "AGREGAR_ALIAS":
        return False

    registrar_decision(
        huella_pago=str(huella_pago),
        id_pago_origen=(
            int(ultima["id_pago_origen"])
            if pd.notna(ultima.get("id_pago_origen"))
            else -1
        ),
        monto=float(ultima["monto"]) if pd.notna(ultima.get("monto")) else 0.0,
        descripcion_pago=str(ultima.get("descripcion_pago", "")),
        accion="REVERTIR",
        comentario=motivo or f"Reversión de decisión previa ({accion}).",
        usuario=usuario,
        estado_decision="REVERTIDA",
        ruta=ruta,
    )
    return True


def decisiones_activas_detalle(ruta: Path = RUTA_DECISIONES) -> pd.DataFrame:
    """Decisiones ACTIVAS (más reciente por huella), ordenadas desc por fecha.

    Pensada para alimentar la tabla de 'Decisiones registradas' del dashboard.
    """
    df = cargar_decisiones(ruta)
    if df.empty:
        return df

    df = _asegurar_columna_estado(df)
    df = df.drop_duplicates(subset=["huella_pago"], keep="last")
    df = df[df["estado_decision"].astype(str).str.upper() == "ACTIVA"]
    if "fecha_decision" in df.columns:
        df = df.sort_values("fecha_decision", ascending=False)
    return df.reset_index(drop=True)


def agregar_alias(
    alias: str,
    cliente_real: str,
    notas: str = "",
    ruta: Path = Path("data/reference/alias_clientes.csv"),
) -> None:
    """Añade un alias al catálogo si no existe ya."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if not ruta.exists():
        pd.DataFrame(columns=["alias", "cliente_real", "notas"]).to_csv(
            ruta, index=False
        )

    df = pd.read_csv(ruta, comment="#")
    alias_norm = str(alias).strip().upper()

    if (
        "alias" in df.columns
        and alias_norm in df["alias"].astype(str).str.upper().values
    ):
        return

    nueva = pd.DataFrame(
        [
            {
                "alias": alias_norm,
                "cliente_real": str(cliente_real).strip().upper(),
                "notas": notas,
            }
        ]
    )
    pd.concat([df, nueva], ignore_index=True).to_csv(ruta, index=False)


# -----------------------------------------------------------------------------
# Historial de pagos procesados
# -----------------------------------------------------------------------------


def _asegurar_historial_existe(ruta: Path = RUTA_HISTORIAL) -> None:
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
    """Añade un pago al historial. Solo debe llamarse para estado ASOCIADO."""
    _asegurar_historial_existe(ruta)

    if fecha_corrida is None:
        fecha_corrida = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    facturas_str = (
        str(facturas_asociadas)
        if isinstance(facturas_asociadas, list)
        else (str(facturas_asociadas) if facturas_asociadas else "")
    )

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
    if not Path(ruta).exists():
        return pd.DataFrame(columns=COLUMNAS_HISTORIAL)
    return pd.read_csv(ruta)


def huellas_ya_procesadas(ruta: Path = RUTA_HISTORIAL) -> set[str]:
    """Conjunto de huellas ya resueltas en corridas previas (lookup O(1))."""
    if not Path(ruta).exists():
        return set()
    df = pd.read_csv(ruta, usecols=["huella_pago"])
    return set(df["huella_pago"].astype(str).tolist())
