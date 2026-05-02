"""Paso 5 — Fusiona cartera + matches en base consolidada y excepciones."""

import pandas as pd

# Estados que requieren acción humana (van a la tabla de excepciones).
# NO_APLICA queda fuera: la analista ya decidió que el pago no es de cartera.
# PENDIENTE_ANALISTA sí entra: caso en espera que se quiere seguir viendo.
ESTADOS_EXCEPCION = [
    "AMBIGUO",
    "NO_IDENTIFICADO",
    "CLIENTE_DESCONOCIDO",
    "PENDIENTE_ANALISTA",
]


# Mapeo de metodo_match (jerga interna) a etiquetas legibles para la analista.
# Lo que ve la analista en el dashboard y en los CSVs exportados.
ORIGEN_POR_METODO = {
    "historial": "Histórico (corrida previa)",
    "exacto": "Automático",
    "acumulado": "Automático",
    "referencia": "Automático",
    "exacto_multiple": "Ambiguo automático",
    "acumulado_multiple": "Ambiguo automático",
    "manual_analista": "Manual (asignación directa)",
    "manual_parcial": "Manual (pago parcial)",
    "manual_pendiente": "Manual (pendiente)",
    "manual_cliente_nuevo": "Manual (cliente nuevo)",
    "manual_no_aplica": "Fuera de cartera",
    "manual_conflicto": "Conflicto manual",
    "ninguno": "Sin resolver",
}


def _derivar_origen(metodo_match) -> str:
    """Traduce metodo_match a una etiqueta legible. Vacíos o desconocidos → 'Sin resolver'."""
    if pd.isna(metodo_match):
        return "Sin resolver"
    return ORIGEN_POR_METODO.get(str(metodo_match), "Sin resolver")


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
    """Retorna {'base_consolidada', 'excepciones'} como DataFrames."""
    asociados = df_matches[df_matches["estado_match"] == "ASOCIADO"]
    filas_aplanadas = [
        {
            "documento": str(doc),
            "id_pago": row["id_pago"],
            "monto_pago_total": row["monto"],
            "metodo_match": row["metodo_match"],
            "fecha_pago": row["fecha"],
        }
        for _, row in asociados.iterrows()
        for doc in row["facturas_asociadas"]
    ]
    df_aplanado = pd.DataFrame(filas_aplanadas)

    base = df_cartera.copy()
    base["documento"] = base["documento"].astype(str)

    if not df_aplanado.empty:
        pagos_por_factura = (
            df_aplanado.groupby("documento")
            .agg(
                id_pago=("id_pago", "first"),
                metodo_match=("metodo_match", "first"),
                fecha_pago=("fecha_pago", "first"),
            )
            .reset_index()
        )
        base = base.merge(pagos_por_factura, on="documento", how="left")
    else:
        base["id_pago"] = None
        base["metodo_match"] = None
        base["fecha_pago"] = pd.NaT

    base["tiene_pago_aplicado"] = base["id_pago"].notna()
    base["estado_factura"] = base.apply(
        lambda r: (
            "PAGADA"
            if r["tiene_pago_aplicado"]
            else ("VENCIDA" if r["dias_vencido"] > 0 else "AL_DIA")
        ),
        axis=1,
    )
    base["prioridad"] = base.apply(
        lambda r: _prioridad(r["dias_vencido"], r["tiene_pago_aplicado"]),
        axis=1,
    )
    base["origen"] = base["metodo_match"].apply(_derivar_origen)

    excepciones = df_matches[df_matches["estado_match"].isin(ESTADOS_EXCEPCION)].copy()
    if not excepciones.empty:
        excepciones["origen"] = excepciones["metodo_match"].apply(_derivar_origen)

    return {
        "base_consolidada": base,
        "excepciones": excepciones,
    }
