"""Paso 1 — Parsea el extracto bancario crudo de Bancolombia (CTE).

El banco entrega un CSV plano sin encabezados, con 10 columnas posicionales.
Cualquier desviación de ese contrato hace fallar el parser temprano.
"""

from __future__ import annotations
from pathlib import Path

import pandas as pd

# Contrato fijo del CSV crudo: 10 columnas en este orden.
# Los campos "_reservado_*" y "_flag" no se usan aguas abajo pero se nombran
# para que un cambio del banco (ej. columnas en distinto orden) sea visible.
_COLUMNAS_CRUDAS = [
    "cuenta",
    "sucursal",
    "_reservado_1",
    "fecha_raw",  # entero YYYYMMDD
    "_reservado_2",
    "valor",  # con signo: + abono, - cargo
    "codigo",
    "descripcion",
    "_flag",
    "_reservado_3",
]

_NUM_COLUMNAS_ESPERADAS = len(_COLUMNAS_CRUDAS)


def parse_extracto(
    ruta_csv: str | Path,
    fecha_desde: str | pd.Timestamp | None = None,
    fecha_hasta: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Devuelve un DataFrame limpio y tipado del extracto.

    El filtro de fechas es opcional y permite excluir movimientos que la
    analista ya conció directamente en SAP. Ambos extremos son inclusivos.
    Expone en df.attrs["descartados_por_filtro"] cuántas filas dejó fuera.
    """
    ruta = Path(ruta_csv)
    if not ruta.exists():
        raise FileNotFoundError(f"No se encontró el archivo: {ruta}")

    df = pd.read_csv(ruta, header=None, encoding="utf-8")

    if df.shape[1] != _NUM_COLUMNAS_ESPERADAS:
        raise ValueError(
            f"El extracto tiene {df.shape[1]} columnas, "
            f"se esperaban {_NUM_COLUMNAS_ESPERADAS}."
        )

    df.columns = _COLUMNAS_CRUDAS

    df["fecha"] = pd.to_datetime(df["fecha_raw"], format="%Y%m%d", errors="coerce")
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df["codigo"] = pd.to_numeric(df["codigo"], errors="coerce").astype("Int64")
    df["descripcion"] = df["descripcion"].astype(str).str.strip().str.upper()
    df["cuenta"] = df["cuenta"].astype(str).str.strip()

    df["valor_abs"] = df["valor"].abs()
    df["tipo_flujo"] = df["valor"].apply(
        lambda v: "ABONO" if v > 0 else ("CARGO" if v < 0 else "NULO")
    )

    descartados_por_filtro = 0
    if fecha_desde is not None or fecha_hasta is not None:
        n_inicial = len(df)

        n_nat = df["fecha"].isna().sum()
        if n_nat > 0:
            print(
                f"⚠️  parser_extracto: {n_nat} fila(s) con fecha inválida "
                f"descartadas por filtro de fechas activo."
            )

        mascara = df["fecha"].notna()
        if fecha_desde is not None:
            mascara &= df["fecha"] >= pd.to_datetime(fecha_desde)
        if fecha_hasta is not None:
            mascara &= df["fecha"] <= pd.to_datetime(fecha_hasta)

        df = df[mascara].copy()
        descartados_por_filtro = n_inicial - len(df)

    columnas_salida = [
        "cuenta",
        "fecha",
        "valor",
        "valor_abs",
        "tipo_flujo",
        "codigo",
        "descripcion",
    ]
    df_salida = df[columnas_salida].reset_index(drop=True)
    df_salida.attrs["descartados_por_filtro"] = descartados_por_filtro
    return df_salida


if __name__ == "__main__":
    ruta = Path(__file__).parent.parent / "data" / "input" / "EXTRACTO_BANCARIO.csv"
    extracto = parse_extracto(ruta)
    print(f"Filas parseadas: {len(extracto)}")
    print(f"Rango de fechas: {extracto['fecha'].min()} → {extracto['fecha'].max()}")
    print(
        f"Abonos: {(extracto['tipo_flujo']=='ABONO').sum()} | "
        f"Cargos: {(extracto['tipo_flujo']=='CARGO').sum()}"
    )
    print("\nPrimeras filas:")
    print(extracto.head().to_string())
