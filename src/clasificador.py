"""
Paso 2 — Clasificador de movimientos bancarios.

Toma el DataFrame del parser y añade una columna 'categoria' con la
clasificación de negocio. Reglas deterministas derivadas del archivo
histórico Mvto_BANCOLOMBIA_CTE_2024.

Cambio clave v2: la regla "PAGO DE PROV" + ABONO precede a cualquier otra,
porque el banco usa ese prefijo cuando un tercero le paga a la empresa
(es decir, es un ingreso de cliente).
"""

import pandas as pd


# Orden estricto: se evalúa de arriba a abajo y la primera coincidencia gana.
# Cada regla: (categoría, lista de palabras clave, restricción de tipo_flujo opcional)
REGLAS = [
    # ⚠ Regla especial: "PAGO DE PROV" con monto positivo es un pago de cliente.
    #    El banco etiqueta así las transferencias ENTRANTES desde proveedores
    #    o desde cuentas de terceros.
    ("PAGO_CLIENTE",      ["PAGO DE PROV", "PAGO DE PROVE"], "ABONO"),

    ("INTERESES_BANCO",   ["INTERESES", "INTERES AHORROS"], None),
    ("IMPUESTO",          ["GMF", "4X1000", "IVA", "RETEFUENTE", "RETENCION"], None),
    ("AJUSTE_CONTABLE",   ["DEBITO POR ABONO", "REVERSION", "AJUSTE"], None),
    ("EGRESO_PROVEEDOR",  ["PAGO A PROV", "PAGO PROV", "TRANSF A PROV"], "CARGO"),
    ("EGRESO_NOMINA",     ["NOMINA", "PAGO EMPLEADO"], "CARGO"),
]


def _clasificar_fila(row):
    desc = row["descripcion_norm"]
    flujo = row["tipo_flujo"]

    for categoria, palabras, flujo_req in REGLAS:
        if flujo_req and flujo != flujo_req:
            continue
        if any(p in desc for p in palabras):
            return categoria

    # Si no cayó en ninguna regla: se decide por el signo
    if flujo == "ABONO":
        return "PAGO_CLIENTE"
    else:
        return "OTRO_EGRESO"


def clasificar_movimientos(df: pd.DataFrame) -> pd.DataFrame:
    """Añade la columna 'categoria' al DataFrame de movimientos."""
    df = df.copy()
    df["categoria"] = df.apply(_clasificar_fila, axis=1)
    return df


if __name__ == "__main__":
    from parser_extracto import parsear_extracto
    df = parsear_extracto("data/input/EXTRACTO_BANCARIO.csv")
    df = clasificar_movimientos(df)
    print(df[["fecha", "monto", "tipo_flujo", "categoria", "descripcion"]].to_string())
    print("\nResumen por categoría:")
    print(df["categoria"].value_counts())
