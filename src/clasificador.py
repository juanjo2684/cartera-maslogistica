"""Paso 2 — Clasifica movimientos bancarios en categorías de negocio."""

import pandas as pd

# Reglas evaluadas en orden; la primera coincidencia gana.
# (categoria, palabras_clave, tipo_flujo_requerido_o_None)
#
# La primera regla es contraintuitiva: "PAGO DE PROV" con monto positivo
# es un INGRESO de cliente, no un egreso a proveedor. Es como Bancolombia
# etiqueta las transferencias entrantes desde cuentas de terceros.
REGLAS = [
    ("PAGO_CLIENTE", ["PAGO DE PROV", "PAGO DE PROVE"], "ABONO"),
    ("INTERESES_BANCO", ["INTERESES", "INTERES AHORROS"], None),
    ("IMPUESTO", ["GMF", "4X1000", "IVA", "RETEFUENTE", "RETENCION"], None),
    ("AJUSTE_CONTABLE", ["DEBITO POR ABONO", "REVERSION", "AJUSTE"], None),
    ("EGRESO_PROVEEDOR", ["PAGO A PROV", "PAGO PROV", "TRANSF A PROV"], "CARGO"),
    ("EGRESO_NOMINA", ["NOMINA", "PAGO EMPLEADO"], "CARGO"),
]


def _clasificar_fila(row):
    desc = row["descripcion_norm"]
    flujo = row["tipo_flujo"]

    for categoria, palabras, flujo_req in REGLAS:
        if flujo_req and flujo != flujo_req:
            continue
        if any(p in desc for p in palabras):
            return categoria

    return "PAGO_CLIENTE" if flujo == "ABONO" else "OTRO_EGRESO"


def clasificar_movimientos(df: pd.DataFrame) -> pd.DataFrame:
    """Añade la columna 'categoria' al DataFrame de movimientos."""
    df = df.copy()
    df["categoria"] = df.apply(_clasificar_fila, axis=1)
    return df


if __name__ == "__main__":
    from parser_extracto import parse_extracto

    df = parse_extracto("data/input/EXTRACTO_BANCARIO.csv")
    df = clasificar_movimientos(df)
    print(df[["fecha", "monto", "tipo_flujo", "categoria", "descripcion"]].to_string())
    print("\nResumen por categoría:")
    print(df["categoria"].value_counts())
