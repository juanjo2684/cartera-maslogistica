"""
Paso 5 — Consolidador.

Fusiona cartera + matches en una base única que alimenta el dashboard.
Produce dos salidas:
  - base_consolidada: una fila por factura, con estado y prioridad.
  - excepciones: pagos que requieren decisión humana
    (AMBIGUO / NO_IDENTIFICADO / CLIENTE_DESCONOCIDO / PENDIENTE_ANALISTA).

Estados que NO generan excepción:
  - ASOCIADO     → pago aplicado a factura(s).
  - NO_APLICA    → la analista ya marcó que el pago no corresponde a cartera.
"""

import pandas as pd


# Estados que aparecen en la tabla de excepciones (requieren acción humana).
# NO_APLICA queda fuera: la analista ya tomó la decisión, no hay que pedírsela
# otra vez. PENDIENTE_ANALISTA sí aparece: es un caso en espera que la analista
# quiere seguir viendo hasta resolverlo.
ESTADOS_EXCEPCION = [
    "AMBIGUO",
    "NO_IDENTIFICADO",
    "CLIENTE_DESCONOCIDO",
    "PENDIENTE_ANALISTA",
]


def _prioridad(dias_vencido: int, tiene_pago_aplicado: bool) -> str:
    if tiene_pago_aplicado and dias_vencido <= 0:
        return "RESUELTO"
    if dias_vencido > 60:
        return "CRITICO"
    if dias_vencido > 30:
        return "ALTO"
    if dias_vencido > 0:
        return "MEDIO"
    return "BAJO"


def consolidar(df_cartera: pd.DataFrame, df_matches: pd.DataFrame) -> dict:
    """Retorna dict con 'base_consolidada' y 'excepciones' como DataFrames."""
    # Aplanar los matches ASOCIADOS: una fila por (pago, factura)
    asociados = df_matches[df_matches["estado_match"] == "ASOCIADO"].copy()
    filas_aplanadas = []
    for _, row in asociados.iterrows():
        facturas = row["facturas_asociadas"]
        for doc in facturas:
            filas_aplanadas.append({
                "documento": str(doc),
                "id_pago": row["id_pago"],
                "monto_pago_total": row["monto"],
                "metodo_match": row["metodo_match"],
                "fecha_pago": row["fecha"],
            })
    df_aplanado = pd.DataFrame(filas_aplanadas)

    # Merge cartera ← pagos aplicados
    base = df_cartera.copy()
    base["documento"] = base["documento"].astype(str)

    if not df_aplanado.empty:
        pagos_por_factura = df_aplanado.groupby("documento").agg(
            id_pago=("id_pago", "first"),
            metodo_match=("metodo_match", "first"),
            fecha_pago=("fecha_pago", "first"),
        ).reset_index()
        base = base.merge(pagos_por_factura, on="documento", how="left")
    else:
        base["id_pago"] = None
        base["metodo_match"] = None
        base["fecha_pago"] = pd.NaT

    base["tiene_pago_aplicado"] = base["id_pago"].notna()
    base["estado_factura"] = base.apply(
        lambda r: "PAGADA" if r["tiene_pago_aplicado"] else (
            "VENCIDA" if r["dias_vencido"] > 0 else "AL_DIA"
        ), axis=1
    )
    base["prioridad"] = base.apply(
        lambda r: _prioridad(r["dias_vencido"], r["tiene_pago_aplicado"]), axis=1
    )

    # Excepciones: todos los estados que requieren decisión humana
    excepciones = df_matches[df_matches["estado_match"].isin(ESTADOS_EXCEPCION)].copy()

    return {
        "base_consolidada": base,
        "excepciones": excepciones,
    }
