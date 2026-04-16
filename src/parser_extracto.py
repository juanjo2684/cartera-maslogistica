"""
Parser del extracto bancario crudo (Bancolombia cuenta corriente).

Contexto:
    El banco entrega el movimiento diario en un CSV plano SIN encabezados,
    con 10 columnas de posición fija. Este módulo lo convierte en un
    DataFrame limpio y tipado, listo para ser clasificado y cruzado con
    la cartera de SAP.

Columnas del CSV (posicionales, siempre en este orden):
    0 → cuenta bancaria (str)         ej. "542-727683-26"
    1 → sucursal (int)                ej. 245
    2 → reservado (vacío)
    3 → fecha (int YYYYMMDD)          ej. 20260407
    4 → reservado (vacío)
    5 → valor con signo (float)       positivo = abono, negativo = cargo
    6 → código interno del banco (int) ej. 1160, 8162, 2999
    7 → descripción (str)             ej. "PAGO A PROV CARLOS ANDRES MONT"
    8 → flag (int, normalmente 0)
    9 → reservado (vacío)
"""

from __future__ import annotations
from pathlib import Path
import pandas as pd


# Orden fijo de columnas esperadas en el CSV crudo.
# Si el banco llegara a cambiar este contrato, el error se levanta
# temprano (mejor fallar rápido que producir basura silenciosa).
_COLUMNAS_CRUDAS = [
    "cuenta",
    "sucursal",
    "_reservado_1",
    "fecha_raw",
    "_reservado_2",
    "valor",
    "codigo",
    "descripcion",
    "_flag",
    "_reservado_3",
]

_NUM_COLUMNAS_ESPERADAS = len(_COLUMNAS_CRUDAS)  # 10


def parse_extracto(ruta_csv: str | Path) -> pd.DataFrame:
    """
    Lee el extracto bancario crudo y devuelve un DataFrame limpio.

    Parameters
    ----------
    ruta_csv : str o Path
        Ruta al archivo CSV plano del banco.

    Returns
    -------
    pd.DataFrame con columnas:
        - cuenta (str)
        - fecha (datetime64)
        - valor (float)          con signo: + abono, - cargo
        - valor_abs (float)      sin signo, útil para matching
        - codigo (int)           código interno del banco
        - descripcion (str)      normalizada (strip + upper)
        - tipo_flujo (str)       "ABONO" o "CARGO"

    Raises
    ------
    ValueError
        Si el CSV no tiene exactamente 10 columnas (el contrato del banco).
    FileNotFoundError
        Si la ruta no existe.
    """
    ruta = Path(ruta_csv)
    if not ruta.exists():
        raise FileNotFoundError(f"No se encontró el archivo: {ruta}")

    # 1. Lectura cruda SIN encabezados (el banco no los manda).
    df = pd.read_csv(ruta, header=None, encoding="utf-8")

    # 2. Validación del contrato: exactamente 10 columnas.
    if df.shape[1] != _NUM_COLUMNAS_ESPERADAS:
        raise ValueError(
            f"El extracto tiene {df.shape[1]} columnas, "
            f"se esperaban {_NUM_COLUMNAS_ESPERADAS}. "
            f"Revisar el formato entregado por el banco."
        )

    # 3. Asignar nombres a las columnas crudas.
    df.columns = _COLUMNAS_CRUDAS

    # 4. Tipado y limpieza.
    # Fecha: entero YYYYMMDD → datetime.
    df["fecha"] = pd.to_datetime(df["fecha_raw"], format="%Y%m%d", errors="coerce")

    # Valor: forzar a float (por si llega como string con espacios).
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")

    # Código: forzar entero (nullable para tolerar vacíos si aparecen).
    df["codigo"] = pd.to_numeric(df["codigo"], errors="coerce").astype("Int64")

    # Descripción: strip y upper. upper porque el matching posterior
    # compara contra nombres de cliente que pueden venir en cualquier caja.
    df["descripcion"] = (
        df["descripcion"].astype(str).str.strip().str.upper()
    )

    # Cuenta: strip (a veces vienen con espacios).
    df["cuenta"] = df["cuenta"].astype(str).str.strip()

    # 5. Columnas derivadas útiles para etapas siguientes.
    df["valor_abs"] = df["valor"].abs()
    df["tipo_flujo"] = df["valor"].apply(
        lambda v: "ABONO" if v > 0 else ("CARGO" if v < 0 else "NULO")
    )

    # 6. Devolver solo las columnas útiles, en orden lógico.
    columnas_salida = [
        "cuenta",
        "fecha",
        "valor",
        "valor_abs",
        "tipo_flujo",
        "codigo",
        "descripcion",
    ]
    return df[columnas_salida].reset_index(drop=True)


if __name__ == "__main__":
    # Prueba rápida cuando se ejecuta el módulo directamente.
    ruta = Path(__file__).parent.parent / "data" / "input" / "EXTRACTO_BANCARIO.csv"
    extracto = parse_extracto(ruta)
    print(f"Filas parseadas: {len(extracto)}")
    print(f"Columnas: {list(extracto.columns)}")
    print(f"Rango de fechas: {extracto['fecha'].min()} → {extracto['fecha'].max()}")
    print(f"Abonos: {(extracto['tipo_flujo']=='ABONO').sum()} | "
          f"Cargos: {(extracto['tipo_flujo']=='CARGO').sum()}")
    print("\nPrimeras filas:")
    print(extracto.to_string())
