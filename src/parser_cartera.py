"""
Paso 3 — Parser de cartera (SAP o semanal).

Auto-detecta el formato del archivo y devuelve un DataFrame con una fila
por factura pendiente, enriquecido con días vencidos y banda de antigüedad.

Cambio clave v2: acepta un parámetro `fecha_corte` para calcular la
antigüedad contra una fecha específica (no necesariamente hoy). Útil para
pruebas con datos históricos y para reproducir reportes de semanas pasadas.
"""

from datetime import date, datetime
from pathlib import Path

import pandas as pd


COLUMNAS_SALIDA = [
    "cliente", "cliente_norm", "documento",
    "fecha_contabilizacion", "fecha_vencimiento",
    "valor_original", "saldo_pendiente",
    "dias_vencido", "banda_antiguedad"
]


def _banda_antiguedad(dias: int) -> str:
    if dias < 0:
        return "AL_DIA"
    if dias <= 30:
        return "0-30"
    if dias <= 60:
        return "31-60"
    if dias <= 90:
        return "61-90"
    if dias <= 120:
        return "91-120"
    return "121+"


def _resolver_fecha_corte(fecha_corte) -> pd.Timestamp:
    """Normaliza la fecha de corte a Timestamp. Si es None, usa hoy."""
    if fecha_corte is None:
        return pd.Timestamp(datetime.now().date())
    if isinstance(fecha_corte, pd.Timestamp):
        return fecha_corte
    if isinstance(fecha_corte, (datetime, date)):
        return pd.Timestamp(fecha_corte)
    # String: dejar que pandas lo parsee
    return pd.Timestamp(fecha_corte)


def parsear_cartera_sap(path: str | Path, fecha_corte=None) -> pd.DataFrame:
    """Parsea el export crudo de SAP. Filtra solo RF con saldo > 0."""
    df = pd.read_excel(path)
    df = df[df["Tipo"] == "RF"].copy()
    df["saldo_pendiente"] = pd.to_numeric(df["Saldo vencido"], errors="coerce")
    df = df[df["saldo_pendiente"] > 0].copy()

    df["cliente"] = df["Nombre SN"].astype(str).str.strip()
    df["cliente_norm"] = df["cliente"].str.upper()
    df["documento"] = df["Nº documento"].astype(str)
    df["fecha_contabilizacion"] = pd.to_datetime(df["Fecha de contabilización"], dayfirst=True, errors="coerce")
    df["fecha_vencimiento"] = pd.to_datetime(df["Fecha de vencimiento"], dayfirst=True, errors="coerce")
    df["valor_original"] = df["saldo_pendiente"]

    corte = _resolver_fecha_corte(fecha_corte)
    df["dias_vencido"] = (corte - df["fecha_vencimiento"]).dt.days
    df["banda_antiguedad"] = df["dias_vencido"].apply(_banda_antiguedad)

    return df[COLUMNAS_SALIDA].reset_index(drop=True)


def parsear_cartera_semanal(path: str | Path, hoja: str | None = None, fecha_corte=None) -> pd.DataFrame:
    """Parsea la cartera semanal. Si no se indica hoja, usa la primera."""
    xls = pd.ExcelFile(path)
    if hoja is None:
        hoja = xls.sheet_names[0]

    df_raw = pd.read_excel(path, sheet_name=hoja, header=None)
    # Fila 0: título. Fila 1: encabezado. Fila 2: sub-encabezado de bandas.
    # Datos desde fila 3. Usamos las primeras 7 u 8 columnas según el formato:
    #  - Cartera semanal 2024 real: 8 columnas (incluye dias_vencimiento_raw).
    #  - Demo / formato reducido: 7 columnas (sin dias_vencimiento_raw).
    # Los días vencidos los recalculamos aquí con fecha_corte, así que no
    # dependemos de esa columna aunque exista.
    nombres_base = [
        "cliente", "documento", "fecha_contabilizacion", "fecha_vencimiento",
        "valor_original", "saldo_vencido", "abono_futuro"
    ]
    num_cols_disponibles = df_raw.shape[1]
    if num_cols_disponibles >= 8:
        df = df_raw.iloc[3:, :8].copy()
        df.columns = nombres_base + ["dias_vencimiento_raw"]
    else:
        df = df_raw.iloc[3:, :7].copy()
        df.columns = nombres_base

    df = df[df["cliente"].notna() & df["documento"].notna()].copy()
    df["saldo_pendiente"] = pd.to_numeric(df["saldo_vencido"], errors="coerce").fillna(0)
    df = df[df["saldo_pendiente"] > 0].copy()

    df["cliente"] = df["cliente"].astype(str).str.strip()
    df["cliente_norm"] = df["cliente"].str.upper()
    df["documento"] = df["documento"].astype(str).str.replace(".0", "", regex=False)
    df["fecha_contabilizacion"] = pd.to_datetime(df["fecha_contabilizacion"], dayfirst=True, errors="coerce")
    df["fecha_vencimiento"] = pd.to_datetime(df["fecha_vencimiento"], dayfirst=True, errors="coerce")
    df["valor_original"] = pd.to_numeric(df["valor_original"], errors="coerce")

    corte = _resolver_fecha_corte(fecha_corte)
    df["dias_vencido"] = (corte - df["fecha_vencimiento"]).dt.days
    df["banda_antiguedad"] = df["dias_vencido"].apply(_banda_antiguedad)

    return df[COLUMNAS_SALIDA].reset_index(drop=True)


def parsear_cartera(path: str | Path, hoja: str | None = None, fecha_corte=None) -> pd.DataFrame:
    """Auto-detecta el formato y delega al parser apropiado."""
    df_preview = pd.read_excel(path, nrows=2)
    if "Tipo" in df_preview.columns:
        return parsear_cartera_sap(path, fecha_corte=fecha_corte)
    else:
        return parsear_cartera_semanal(path, hoja=hoja, fecha_corte=fecha_corte)


if __name__ == "__main__":
    df = parsear_cartera("data/input/Cartera_semanal_2024.xlsx", fecha_corte="2024-12-30")
    print(f"Facturas abiertas: {len(df)}")
    print(f"Clientes únicos: {df['cliente_norm'].nunique()}")
    print(f"Saldo total: ${df['saldo_pendiente'].sum():,.0f}")
    print("\nDistribución por banda (con fecha_corte=2024-12-30):")
    print(df["banda_antiguedad"].value_counts())
