"""Plantillas de correos de seguimiento de cartera para +logística.

Este módulo concentra los textos de correo que la analista usa para gestionar
cartera. La etapa de gestión se deriva de la banda de antigüedad más vencida
del cliente. Los textos provienen del documento de copys oficial de la empresa.

Mapeo banda -> etapa:
  AL_DIA          -> SEMANA_0   (informativo)
  0-30, 31-60     -> SEMANA_1_3 (cobro normal)
  61-90           -> SEMANA_4   (preaviso de suspension)
  91-120          -> SEMANA_5   (preaviso reiterado, fecha limite)
  121+            -> SEMANA_6   (notificacion de suspension)
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

# =============================================================================
# Plantillas de cuerpo de correo
# =============================================================================
# Placeholders soportados:
#   {cliente}         -> nombre del cliente
#   {tabla_facturas}  -> tabla Markdown con las facturas pendientes
#   {fecha_limite}    -> fecha sugerida para regularizar (Semanas 4 y 5)

PLANTILLA_SEMANA_0 = """\
Buenas tardes, Señores {cliente}

¡Deseándoles un excelente día!

+LOGISTICA promueve una correcta información respecto a la cartera, para que \
se encuentre recibida y actualizada entre las partes, por ello relacionamos a \
continuación el detalle de esta a la fecha de hoy.

{tabla_facturas}

En caso de presentar alguna inconsistencia, no duden en contactarnos al correo \
cartera@maslogistica.com.co y/o WhatsApp 313 7060368 para brindarles solución \
al respecto si es el caso.

Saludos.
"""

PLANTILLA_SEMANA_1_3 = """\
Buenas tardes, Señores {cliente}

¡Deseándoles un excelente día!

+LOGISTICA le informa que a la fecha nos registran facturas pendientes de pago \
que sobrepasan los límites de crédito establecido, por ello le solicitamos muy \
amablemente poner al día sus obligaciones lo antes posible con el fin de \
evitar suspensiones en el servicio.

En caso de haber realizado el pago correspondiente por favor enviarnos el \
respectivo comprobante junto con el detalle y las deducciones aplicadas al \
correo cartera@maslogistica.com.co y omitir el mensaje anterior.

A continuación, relacionamos la cartera vigente a la fecha para la respectiva gestión:

{tabla_facturas}

Saludos.

(En caso de no ser la persona encargada, favor dirigir a quien corresponda.)
"""

PLANTILLA_SEMANA_4 = """\
Buenas tardes, Señores {cliente}

¡Deseándoles un excelente día!

+LOGISTICA le informa que no hemos recibido pago de sus obligaciones \
relacionadas en comunicaciones anteriores, por ello le solicitamos poner al \
día sus obligaciones vencidas lo antes posible, antes del {fecha_limite}, \
para evitar suspensión en el servicio.

En caso de haber realizado el pago correspondiente por favor enviarnos el \
respectivo comprobante junto con el detalle y las deducciones aplicadas al \
correo cartera@maslogistica.com.co y omitir el mensaje anterior.

A continuación, relacionamos la cartera vigente a la fecha para la respectiva gestión:

{tabla_facturas}

Saludos.
"""

PLANTILLA_SEMANA_5 = """\
Buenas tardes, Señores {cliente}

¡Deseándoles un excelente día!

+LOGISTICA reitera que no hemos recibido pago de sus obligaciones relacionadas \
en comunicaciones anteriores, por ello le solicitamos poner al día sus \
obligaciones antes del {fecha_limite}, con el respectivo compromiso de pago \
de la cartera vencida a la fecha, para evitar suspensión inmediata en el servicio.

En caso de haber realizado el pago correspondiente por favor enviarnos el \
respectivo comprobante junto con el detalle y las deducciones aplicadas al \
correo cartera@maslogistica.com.co y omitir el mensaje anterior.

A continuación, relacionamos la cartera vigente a la fecha para la respectiva gestión:

{tabla_facturas}

Saludos.
"""

PLANTILLA_SEMANA_6 = """\
Buen día, Señores {cliente}

¡Deseándoles un excelente día!

+LOGISTICA notifica que a partir del día de hoy se procede con la suspensión \
inmediata del servicio, debido a la falta de pago de las obligaciones \
pendientes a la fecha.

Lo invitamos a poner al día sus obligaciones, mediante un compromiso de pago \
que permita a un futuro cercano la reactivación del servicio, como también \
para evitar un reporte negativo en las centrales de crédito Datacrédito y \
posibles pagos adicionales como honorarios y gastos de cobranza.

A continuación, relacionamos la cartera vigente a la fecha:

{tabla_facturas}

Cualquier inquietud no duden en contactarnos.

Saludos.
"""

# =============================================================================
# Asuntos por etapa
# =============================================================================

ASUNTOS = {
    "SEMANA_0": "Actualización de cartera — {cliente}",
    "SEMANA_1_3": "Cobro de cartera — {cliente}",
    "SEMANA_4": "Preaviso de suspensión de servicio — {cliente}",
    "SEMANA_5": "URGENTE: Preaviso reiterado de suspensión — {cliente}",
    "SEMANA_6": "Notificación de suspensión de servicio — {cliente}",
}

PLANTILLAS = {
    "SEMANA_0": PLANTILLA_SEMANA_0,
    "SEMANA_1_3": PLANTILLA_SEMANA_1_3,
    "SEMANA_4": PLANTILLA_SEMANA_4,
    "SEMANA_5": PLANTILLA_SEMANA_5,
    "SEMANA_6": PLANTILLA_SEMANA_6,
}

# Etiquetas legibles para mostrar en UI.
ETIQUETAS_ETAPA = {
    "SEMANA_0": "Semana 0 — Informativo",
    "SEMANA_1_3": "Semanas 1-3 — Cobro normal",
    "SEMANA_4": "Semana 4 — Preaviso de suspensión",
    "SEMANA_5": "Semana 5 — Preaviso reiterado",
    "SEMANA_6": "Semana 6 — Notificación de suspensión",
}

# Mapeo banda -> etapa. La banda mas vencida del cliente determina la etapa.
_MAPA_BANDA_ETAPA = {
    "AL_DIA": "SEMANA_0",
    "0-30": "SEMANA_1_3",
    "31-60": "SEMANA_1_3",
    "61-90": "SEMANA_4",
    "91-120": "SEMANA_5",
    "121+": "SEMANA_6",
}


# =============================================================================
# Funciones publicas
# =============================================================================


def derivar_etapa(banda_mas_vencida: str) -> str:
    """Mapea la banda mas vencida del cliente a una clave de etapa."""
    return _MAPA_BANDA_ETAPA.get(banda_mas_vencida, "SEMANA_1_3")


def construir_correo(
    cliente: str,
    df_facturas_cliente: pd.DataFrame,
    fecha_hoy: date | None = None,
) -> dict:
    """Construye asunto y cuerpo del correo para un cliente.

    Args:
        cliente: nombre del cliente (se inserta en saludo y asunto).
        df_facturas_cliente: facturas abiertas del cliente. Debe contener
            las columnas: documento, fecha_vencimiento, dias_vencido,
            saldo_pendiente, banda_antiguedad.
        fecha_hoy: fecha de referencia para calcular fecha_limite.
            Default: hoy.

    Returns:
        dict con claves: asunto, cuerpo, etapa, banda_max, etiqueta_etapa.
    """
    if fecha_hoy is None:
        fecha_hoy = date.today()

    banda_max = _banda_mas_vencida(df_facturas_cliente)
    etapa = derivar_etapa(banda_max)

    # Fecha limite sugerida: una semana adelante. La operadora la edita si quiere.
    fecha_limite = _formatear_fecha_es(fecha_hoy + timedelta(days=7))

    tabla = _formatear_tabla_facturas(df_facturas_cliente)

    cuerpo = PLANTILLAS[etapa].format(
        cliente=cliente,
        tabla_facturas=tabla,
        fecha_limite=fecha_limite,
    )
    asunto = ASUNTOS[etapa].format(cliente=cliente)

    return {
        "asunto": asunto,
        "cuerpo": cuerpo,
        "etapa": etapa,
        "banda_max": banda_max,
        "etiqueta_etapa": ETIQUETAS_ETAPA[etapa],
    }


# =============================================================================
# Helpers internos
# =============================================================================

# Orden de severidad ascendente. La banda con mayor indice gana.
_ORDEN_BANDAS = ["AL_DIA", "0-30", "31-60", "61-90", "91-120", "121+"]

_MESES_ES = [
    "",
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


def _formatear_fecha_es(d: date) -> str:
    """Formatea una fecha como '09 de mayo de 2026' sin depender del locale."""
    return f"{d.day:02d} de {_MESES_ES[d.month]} de {d.year}"


def _banda_mas_vencida(df: pd.DataFrame) -> str:
    """Devuelve la banda mas severa presente en el DataFrame."""
    if df.empty or "banda_antiguedad" not in df.columns:
        return "AL_DIA"
    presentes = set(df["banda_antiguedad"].dropna().astype(str).unique())
    for banda in reversed(_ORDEN_BANDAS):
        if banda in presentes:
            return banda
    return "AL_DIA"


def _formatear_tabla_facturas(df: pd.DataFrame) -> str:
    """Construye una tabla Markdown con las facturas del cliente.

    Gmail y Outlook web renderizan tablas Markdown al pegar. Si la operadora
    pega en un cliente que no las renderiza, los caracteres `|` y `-` quedan
    visibles pero el contenido sigue siendo legible.
    """
    if df.empty:
        return "_(Sin facturas pendientes)_"

    # Ordenar por dias vencido descendente para mostrar primero las criticas.
    df_ord = df.sort_values("dias_vencido", ascending=False).copy()

    lineas = [
        "| Documento | Vencimiento | Días vencido | Saldo |",
        "|---|---|---:|---:|",
    ]
    total = 0
    for _, fila in df_ord.iterrows():
        documento = str(fila.get("documento", "")).strip()
        venc = pd.to_datetime(fila.get("fecha_vencimiento")).strftime("%Y-%m-%d")
        dias = int(fila.get("dias_vencido", 0))
        saldo = float(fila.get("saldo_pendiente", 0))
        total += saldo
        lineas.append(f"| {documento} | {venc} | {dias} | ${saldo:,.0f} |")

    lineas.append(f"| **TOTAL** |  |  | **${total:,.0f}** |")
    return "\n".join(lineas)
