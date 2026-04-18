"""
Paso 4 — Motor de matching pago ↔ factura(s).

Cascada:
  0. Consulta registro de decisiones previas de la analista
     (data/output/decisiones_analista.csv). Si el pago ya tiene decisión,
     se aplica directamente sin volver a evaluar.
  1. Consulta tabla de alias (data/reference/alias_clientes.csv) para
     resolver el nombre del cliente si viene con un alias conocido.
  2. Match exacto por valor.
  3. Match acumulado.
  4. Match por referencia (nº de factura en la descripción).

Estados posibles:
  - ASOCIADO             → pago casado con una o más facturas con confianza.
  - AMBIGUO              → múltiples candidatos plausibles; requiere decisión humana.
  - NO_IDENTIFICADO      → cliente sí existe en cartera, pero ninguna factura/combo coincide.
  - CLIENTE_DESCONOCIDO  → la descripción no resuelve a ningún cliente de la cartera
                           ni existe un alias registrado.
  - PENDIENTE_ANALISTA   → la analista decidió 'dejar pendiente' en una corrida previa.
  - NO_APLICA            → la analista decidió 'no corresponde a cartera'.
"""

from itertools import combinations
from pathlib import Path

import pandas as pd

from registro_decisiones import decisiones_por_huella, generar_huella_pago


TOLERANCIA_VALOR = 1.0
MAX_FACTURAS_COMBINACION = 4
ALIAS_PATH_DEFAULT = Path("data/reference/alias_clientes.csv")


# -----------------------------------------------------------------------------
# Manejo de alias
# -----------------------------------------------------------------------------

def cargar_alias(path: str | Path = ALIAS_PATH_DEFAULT) -> dict[str, str]:
    """
    Carga el catálogo de alias. Retorna dict alias_norm → cliente_norm.
    Si el archivo no existe, retorna un dict vacío (sin alias).

    Formato esperado del CSV:
        alias,cliente_real
        BTG PACTUAL SA,NOMBRE OFICIAL DEL CLIENTE SAS
        TRANSP LOGITRANS,TRANSPORTES LOGITRANS SA
    """
    path = Path(path)
    if not path.exists():
        return {}

    df = pd.read_csv(path)
    df["alias"] = df["alias"].astype(str).str.upper().str.strip()
    df["cliente_real"] = df["cliente_real"].astype(str).str.upper().str.strip()
    return dict(zip(df["alias"], df["cliente_real"]))


# -----------------------------------------------------------------------------
# Identificación del cliente
# -----------------------------------------------------------------------------

def _buscar_en_alias(desc: str, alias_map: dict[str, str]) -> str | None:
    """Si la descripción contiene algún alias registrado, retorna el cliente real."""
    for alias, cliente_real in alias_map.items():
        if alias and alias in desc:
            return cliente_real
    return None


def _buscar_cliente_en_cartera(desc: str, clientes_norm: list[str]) -> str | None:
    """Busca si alguna cadena de nombre de cliente aparece en la descripción."""
    for cliente in clientes_norm:
        if cliente and cliente in desc:
            return cliente
        tokens = [t for t in cliente.split() if len(t) > 3]
        for tok in tokens:
            if tok in desc:
                return cliente
    return None


# -----------------------------------------------------------------------------
# Lógica de matching por nivel
# -----------------------------------------------------------------------------

def _match_exacto(monto: float, facturas_cliente: pd.DataFrame) -> list[str]:
    coincidencias = facturas_cliente[
        (facturas_cliente["saldo_pendiente"] - monto).abs() <= TOLERANCIA_VALOR
    ]
    return coincidencias["documento"].tolist()


def _match_acumulado(monto: float, facturas_cliente: pd.DataFrame) -> list[list[str]]:
    facturas = facturas_cliente[["documento", "saldo_pendiente"]].values.tolist()
    if len(facturas) > 15:
        return []

    combinaciones_validas = []
    for k in range(2, min(MAX_FACTURAS_COMBINACION, len(facturas)) + 1):
        for combo in combinations(facturas, k):
            suma = sum(v for _, v in combo)
            if abs(suma - monto) <= TOLERANCIA_VALOR:
                combinaciones_validas.append([doc for doc, _ in combo])
    return combinaciones_validas


def _match_por_referencia(desc: str, facturas_cliente: pd.DataFrame) -> list[str]:
    hits = []
    for doc in facturas_cliente["documento"]:
        if doc and str(doc) in desc:
            hits.append(doc)
    return hits


# -----------------------------------------------------------------------------
# Aplicación de decisiones previas de la analista (Etapa B)
# -----------------------------------------------------------------------------

def _aplicar_decision_previa(
    idx: int,
    row: pd.Series,
    decision: dict,
) -> dict | None:
    """
    Traduce una decisión registrada por la analista en un resultado de matching.

    Retorna un dict con el mismo shape que los demás resultados del matcher,
    o None si la decisión fue AGREGAR_ALIAS (en ese caso se debe re-ejecutar
    la cascada con el alias ya actualizado — la decisión fue una mejora del
    dato de referencia, no una asignación directa).
    """
    accion = str(decision.get("accion", "")).strip().upper()
    base_resultado = {
        "id_pago": idx,
        "fecha": row["fecha"],
        "monto": row["monto"],
        "descripcion": row["descripcion"],
    }

    if accion == "APLICAR_FACTURA":
        factura = str(decision.get("factura_asignada", "")).strip()
        cliente = str(decision.get("cliente_asignado", "")).strip() or None
        return {
            **base_resultado,
            "cliente_identificado": cliente,
            "estado_match": "ASOCIADO",
            "metodo_match": "manual_analista",
            "metodo_cliente": "manual",
            "facturas_asociadas": [factura] if factura else [],
            "observacion": f"Asociación manual registrada el {decision.get('fecha_decision', '')}.",
        }

    if accion == "PAGO_PARCIAL":
        cliente = str(decision.get("cliente_asignado", "")).strip() or None
        return {
            **base_resultado,
            "cliente_identificado": cliente,
            "estado_match": "NO_IDENTIFICADO",
            "metodo_match": "manual_parcial",
            "metodo_cliente": "manual",
            "facturas_asociadas": [],
            "observacion": "Marcado como pago parcial por la analista; conciliación pendiente.",
        }

    if accion == "PENDIENTE":
        cliente = str(decision.get("cliente_asignado", "")).strip() or None
        return {
            **base_resultado,
            "cliente_identificado": cliente,
            "estado_match": "PENDIENTE_ANALISTA",
            "metodo_match": "manual_pendiente",
            "metodo_cliente": "manual",
            "facturas_asociadas": [],
            "observacion": "Caso dejado en pendiente por la analista — investigación con cliente en curso.",
        }

    if accion == "NO_CORRESPONDE":
        return {
            **base_resultado,
            "cliente_identificado": None,
            "estado_match": "NO_APLICA",
            "metodo_match": "manual_no_aplica",
            "metodo_cliente": "manual",
            "facturas_asociadas": [],
            "observacion": "Marcado como ajeno a cartera por la analista.",
        }

    if accion == "CLIENTE_NUEVO":
        cliente = str(decision.get("cliente_asignado", "")).strip() or None
        return {
            **base_resultado,
            "cliente_identificado": cliente,
            "estado_match": "NO_IDENTIFICADO",
            "metodo_match": "manual_cliente_nuevo",
            "metodo_cliente": "manual",
            "facturas_asociadas": [],
            "observacion": "Cliente nuevo registrado por la analista; pendiente de creación en SAP.",
        }

    if accion == "AGREGAR_ALIAS":
        # No aplica directo: el alias ya fue añadido al catálogo desde la UI,
        # así que la cascada normal lo va a resolver correctamente.
        return None

    # Acción desconocida — dejar que la cascada lo evalúe
    return None


# -----------------------------------------------------------------------------
# Orquestación del matching
# -----------------------------------------------------------------------------

def matchear_pagos(
    df_pagos: pd.DataFrame,
    df_cartera: pd.DataFrame,
    alias_path: str | Path = ALIAS_PATH_DEFAULT,
    decisiones_path: str | Path | None = None,
) -> pd.DataFrame:
    """
    Dado el DataFrame de pagos (con columna 'categoria') y la cartera,
    retorna un DataFrame con el estado del matching por cada pago.

    Si existe un registro de decisiones previas de la analista, lo consulta
    primero: los pagos con decisión registrada se aplican directamente sin
    re-evaluar la cascada, preservando trazabilidad.
    """
    df = df_pagos[df_pagos["categoria"] == "PAGO_CLIENTE"].copy().reset_index(drop=True)

    alias_map = cargar_alias(alias_path)
    clientes_cartera = df_cartera["cliente_norm"].unique().tolist()

    # Cargar decisiones previas (si existen). Indexadas por huella.
    if decisiones_path is not None:
        decisiones = decisiones_por_huella(Path(decisiones_path))
    else:
        decisiones = decisiones_por_huella()

    resultados = []
    contador_decisiones_aplicadas = 0

    for idx, row in df.iterrows():
        desc = row["descripcion_norm"]
        monto = row["monto"]

        # --- PASO 0: ¿hay decisión previa para esta huella? ---
        huella = generar_huella_pago(desc, monto, row["fecha"])
        if huella in decisiones:
            resultado_previo = _aplicar_decision_previa(idx, row, decisiones[huella])
            if resultado_previo is not None:
                resultados.append(resultado_previo)
                contador_decisiones_aplicadas += 1
                continue
            # Si es None, es AGREGAR_ALIAS: caemos a la cascada normal
            # (el alias ya debe estar en el catálogo).

        # --- Cascada normal ---
        # Paso 1: ¿Está en el catálogo de alias?
        cliente_id = _buscar_en_alias(desc, alias_map)
        metodo_cliente = "alias" if cliente_id else None

        # Si no, buscar directamente en la cartera
        if cliente_id is None:
            cliente_id = _buscar_cliente_en_cartera(desc, clientes_cartera)
            metodo_cliente = "directo" if cliente_id else None

        if cliente_id is None:
            # No hay forma de saber a qué cliente corresponde
            resultados.append({
                "id_pago": idx, "fecha": row["fecha"], "monto": monto,
                "descripcion": row["descripcion"],
                "cliente_identificado": None,
                "estado_match": "CLIENTE_DESCONOCIDO",
                "metodo_match": "ninguno",
                "metodo_cliente": "ninguno",
                "facturas_asociadas": [],
                "observacion": "Cliente no reconocido. Revisar si es nuevo, si falta un alias, o si es un ingreso ajeno a cartera.",
            })
            continue

        # Verificar si el cliente identificado tiene facturas en la cartera
        facturas_cliente = df_cartera[df_cartera["cliente_norm"] == cliente_id]
        if facturas_cliente.empty:
            # El alias apuntaba a un cliente que no tiene cartera abierta
            resultados.append({
                "id_pago": idx, "fecha": row["fecha"], "monto": monto,
                "descripcion": row["descripcion"],
                "cliente_identificado": cliente_id,
                "estado_match": "NO_IDENTIFICADO",
                "metodo_match": "ninguno",
                "metodo_cliente": metodo_cliente,
                "facturas_asociadas": [],
                "observacion": "Cliente existe pero no tiene facturas abiertas en cartera.",
            })
            continue

        # Cascada de 3 niveles
        hits = _match_exacto(monto, facturas_cliente)
        if len(hits) == 1:
            resultados.append({
                "id_pago": idx, "fecha": row["fecha"], "monto": monto,
                "descripcion": row["descripcion"], "cliente_identificado": cliente_id,
                "estado_match": "ASOCIADO", "metodo_match": "exacto",
                "metodo_cliente": metodo_cliente,
                "facturas_asociadas": hits, "observacion": "",
            })
            continue
        elif len(hits) > 1:
            resultados.append({
                "id_pago": idx, "fecha": row["fecha"], "monto": monto,
                "descripcion": row["descripcion"], "cliente_identificado": cliente_id,
                "estado_match": "AMBIGUO", "metodo_match": "exacto_multiple",
                "metodo_cliente": metodo_cliente,
                "facturas_asociadas": hits,
                "observacion": f"{len(hits)} facturas con el mismo valor.",
            })
            continue

        combos = _match_acumulado(monto, facturas_cliente)
        if len(combos) == 1:
            resultados.append({
                "id_pago": idx, "fecha": row["fecha"], "monto": monto,
                "descripcion": row["descripcion"], "cliente_identificado": cliente_id,
                "estado_match": "ASOCIADO", "metodo_match": "acumulado",
                "metodo_cliente": metodo_cliente,
                "facturas_asociadas": combos[0], "observacion": "",
            })
            continue
        elif len(combos) > 1:
            resultados.append({
                "id_pago": idx, "fecha": row["fecha"], "monto": monto,
                "descripcion": row["descripcion"], "cliente_identificado": cliente_id,
                "estado_match": "AMBIGUO", "metodo_match": "acumulado_multiple",
                "metodo_cliente": metodo_cliente,
                "facturas_asociadas": combos[0],
                "observacion": f"{len(combos)} combinaciones posibles.",
            })
            continue

        hits_ref = _match_por_referencia(desc, facturas_cliente)
        if hits_ref:
            resultados.append({
                "id_pago": idx, "fecha": row["fecha"], "monto": monto,
                "descripcion": row["descripcion"], "cliente_identificado": cliente_id,
                "estado_match": "ASOCIADO", "metodo_match": "referencia",
                "metodo_cliente": metodo_cliente,
                "facturas_asociadas": hits_ref, "observacion": "",
            })
            continue

        # Cliente existe, pero ninguna factura/combinación matchea
        resultados.append({
            "id_pago": idx, "fecha": row["fecha"], "monto": monto,
            "descripcion": row["descripcion"], "cliente_identificado": cliente_id,
            "estado_match": "NO_IDENTIFICADO", "metodo_match": "ninguno",
            "metodo_cliente": metodo_cliente,
            "facturas_asociadas": [],
            "observacion": "Cliente identificado pero ninguna factura coincide (posible pago parcial, adelantado o factura no cargada).",
        })

    df_resultado = pd.DataFrame(resultados)
    # Adjuntamos el contador como atributo para que run_pipeline pueda reportarlo
    # sin cambiar la firma de retorno (que es la que usa el resto del código).
    df_resultado.attrs["decisiones_previas_aplicadas"] = contador_decisiones_aplicadas
    return df_resultado
