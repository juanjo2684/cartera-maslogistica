"""Paso 4 — Motor de matching pago ↔ factura(s).

Cascada por pago:
  0.   YA_PROCESADO si la huella está en el historial (SAP ya lo conció).
  0.5. Aplicar decisión previa de la analista, si existe y sigue siendo válida.
  1.   Identificar cliente por alias o por nombre en la cartera.
  2.   Match exacto por monto.
  3.   Match acumulado (combinación de facturas que sume el monto).
  4.   Match por referencia (nº de factura en la descripción).

Estados: YA_PROCESADO, ASOCIADO, AMBIGUO, NO_IDENTIFICADO,
         CLIENTE_DESCONOCIDO, PENDIENTE_ANALISTA, NO_APLICA.
"""

from itertools import combinations
from pathlib import Path

import pandas as pd

from registro_decisiones import (
    decisiones_por_huella,
    generar_huella_pago,
    huellas_ya_procesadas,
)

TOLERANCIA_VALOR = 1.0
MAX_FACTURAS_COMBINACION = 4
ALIAS_PATH_DEFAULT = Path("data/reference/alias_clientes.csv")

# Sentinel: una decisión histórica que apunta a una factura ya inexistente.
# Distinto de None (que significa AGREGAR_ALIAS y también cae a cascada).
DECISION_DESCARTADA = {"_descartar_decision": True}


# -----------------------------------------------------------------------------
# Construcción de resultados
# -----------------------------------------------------------------------------


def _resultado(
    idx,
    row,
    *,
    cliente=None,
    estado="NO_IDENTIFICADO",
    metodo_match="ninguno",
    metodo_cliente="ninguno",
    facturas=None,
    observacion="",
) -> dict:
    """Construye un dict de resultado con shape uniforme."""
    return {
        "id_pago": idx,
        "fecha": row["fecha"],
        "monto": row["monto"],
        "descripcion": row["descripcion"],
        "cliente_identificado": cliente,
        "estado_match": estado,
        "metodo_match": metodo_match,
        "metodo_cliente": metodo_cliente,
        "facturas_asociadas": facturas or [],
        "observacion": observacion,
    }


# -----------------------------------------------------------------------------
# Alias e identificación de cliente
# -----------------------------------------------------------------------------


def cargar_alias(path: str | Path = ALIAS_PATH_DEFAULT) -> dict[str, str]:
    """Catálogo alias → cliente_real. Vacío si el archivo no existe."""
    path = Path(path)
    if not path.exists():
        return {}

    df = pd.read_csv(path)
    df["alias"] = df["alias"].astype(str).str.upper().str.strip()
    df["cliente_real"] = df["cliente_real"].astype(str).str.upper().str.strip()
    return dict(zip(df["alias"], df["cliente_real"]))


def _buscar_en_alias(desc: str, alias_map: dict[str, str]) -> str | None:
    for alias, cliente_real in alias_map.items():
        if alias and alias in desc:
            return cliente_real
    return None


def _buscar_cliente_en_cartera(desc: str, clientes_norm: list[str]) -> str | None:
    for cliente in clientes_norm:
        if cliente and cliente in desc:
            return cliente
        for tok in cliente.split():
            if len(tok) > 3 and tok in desc:
                return cliente
    return None


# -----------------------------------------------------------------------------
# Lógica de matching
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

    combos = []
    for k in range(2, min(MAX_FACTURAS_COMBINACION, len(facturas)) + 1):
        for combo in combinations(facturas, k):
            if abs(sum(v for _, v in combo) - monto) <= TOLERANCIA_VALOR:
                combos.append([doc for doc, _ in combo])
    return combos


def _match_por_referencia(desc: str, facturas_cliente: pd.DataFrame) -> list[str]:
    return [doc for doc in facturas_cliente["documento"] if doc and str(doc) in desc]


# -----------------------------------------------------------------------------
# Decisiones previas de la analista
# -----------------------------------------------------------------------------


def _facturas_vigentes(
    documentos: list[str],
    df_cartera: pd.DataFrame,
) -> tuple[bool, list[str]]:
    """Verifica que todos los documentos sigan en la cartera actual."""
    documentos_set = {str(d).strip() for d in documentos if d}
    if not documentos_set:
        return True, []
    docs_cartera = set(df_cartera["documento"].astype(str).str.strip())
    faltantes = sorted(documentos_set - docs_cartera)
    return len(faltantes) == 0, faltantes


def _facturas_en_conflicto(decisiones: dict[str, dict]) -> set[str]:
    """Documentos reclamados por más de una decisión APLICAR_FACTURA activa.

    Si la analista tiene N decisiones activas que apuntan a la misma factura,
    aplicar las N como ASOCIADO crearía duplicados que el consolidador
    silenciaría con groupby.first(). En lugar de eso, marcamos cada uno
    como AMBIGUO para que la analista reasigne.
    """
    conteo: dict[str, int] = {}
    for decision in decisiones.values():
        if str(decision.get("accion", "")).strip().upper() != "APLICAR_FACTURA":
            continue
        factura = str(decision.get("factura_asignada", "")).strip()
        if not factura:
            continue
        conteo[factura] = conteo.get(factura, 0) + 1
    return {f for f, n in conteo.items() if n > 1}


def _aplicar_decision_previa(
    idx: int,
    row: pd.Series,
    decision: dict,
    df_cartera: pd.DataFrame,
    facturas_conflicto: set[str],
) -> dict | None:
    """Traduce una decisión registrada en un resultado de matching.

    Retorna None si la decisión fue AGREGAR_ALIAS (la cascada normal lo
    resolverá con el alias actualizado), DECISION_DESCARTADA si la factura
    ya no está en cartera, o un dict con el resultado en cualquier otro caso.
    """
    accion = str(decision.get("accion", "")).strip().upper()
    fecha_dec = decision.get("fecha_decision", "")

    if accion == "APLICAR_FACTURA":
        factura = str(decision.get("factura_asignada", "")).strip()
        cliente = str(decision.get("cliente_asignado", "")).strip() or None

        # Validación defensiva: la factura debe seguir vigente.
        vigentes, faltantes = _facturas_vigentes(
            [factura] if factura else [], df_cartera
        )
        if not vigentes:
            print(
                "[matcher] Decisión histórica descartada por factura(s) ausente(s) en cartera.\n"
                f"          id_pago={idx} fecha={row['fecha']} "
                f"monto={row['monto']} descripcion={row['descripcion']!r}\n"
                f"          documentos_faltantes={faltantes} "
                "→ el pago vuelve a la cascada normal."
            )
            return DECISION_DESCARTADA

        # Chequeo de conflicto entre decisiones manuales.
        # Si más de una decisión activa apunta a la misma factura, no podemos
        # aplicar ninguna sin perder pagos. Marcamos como AMBIGUO para que la
        # analista reasigne.
        if factura in facturas_conflicto:
            return _resultado(
                idx,
                row,
                cliente=cliente,
                estado="AMBIGUO",
                metodo_match="manual_conflicto",
                metodo_cliente="manual",
                facturas=[factura],
                observacion=(
                    f"Conflicto: múltiples decisiones manuales apuntan a la factura "
                    f"{factura}. Reasignar uno de los pagos."
                ),
            )

        return _resultado(
            idx,
            row,
            cliente=cliente,
            estado="ASOCIADO",
            metodo_match="manual_analista",
            metodo_cliente="manual",
            facturas=[factura] if factura else [],
            observacion=f"Asociación manual registrada el {fecha_dec}.",
        )

    if accion == "PAGO_PARCIAL":
        return _resultado(
            idx,
            row,
            cliente=str(decision.get("cliente_asignado", "")).strip() or None,
            estado="NO_IDENTIFICADO",
            metodo_match="manual_parcial",
            metodo_cliente="manual",
            observacion="Marcado como pago parcial por la analista; conciliación pendiente.",
        )

    if accion == "PENDIENTE":
        return _resultado(
            idx,
            row,
            cliente=str(decision.get("cliente_asignado", "")).strip() or None,
            estado="PENDIENTE_ANALISTA",
            metodo_match="manual_pendiente",
            metodo_cliente="manual",
            observacion="Caso dejado en pendiente por la analista — investigación con cliente en curso.",
        )

    if accion == "NO_CORRESPONDE":
        return _resultado(
            idx,
            row,
            estado="NO_APLICA",
            metodo_match="manual_no_aplica",
            metodo_cliente="manual",
            observacion="Marcado como ajeno a cartera por la analista.",
        )

    if accion == "CLIENTE_NUEVO":
        return _resultado(
            idx,
            row,
            cliente=str(decision.get("cliente_asignado", "")).strip() or None,
            estado="NO_IDENTIFICADO",
            metodo_match="manual_cliente_nuevo",
            metodo_cliente="manual",
            observacion="Cliente nuevo registrado por la analista; pendiente de creación en SAP.",
        )

    # AGREGAR_ALIAS o acción desconocida: la cascada normal evalúa.
    return None


# -----------------------------------------------------------------------------
# Orquestación
# -----------------------------------------------------------------------------


def matchear_pagos(
    df_pagos: pd.DataFrame,
    df_cartera: pd.DataFrame,
    alias_path: str | Path = ALIAS_PATH_DEFAULT,
    decisiones_path: str | Path | None = None,
    historial_path: str | Path | None = None,
) -> pd.DataFrame:
    """Aplica la cascada de matching a los pagos de cliente."""
    df = df_pagos[df_pagos["categoria"] == "PAGO_CLIENTE"].copy().reset_index(drop=True)

    alias_map = cargar_alias(alias_path)
    clientes_cartera = df_cartera["cliente_norm"].unique().tolist()

    huellas_historial = (
        huellas_ya_procesadas(Path(historial_path))
        if historial_path
        else huellas_ya_procesadas()
    )
    decisiones = (
        decisiones_por_huella(Path(decisiones_path))
        if decisiones_path
        else decisiones_por_huella()
    )

    # Detectar facturas reclamadas por más de una decisión APLICAR_FACTURA activa.
    # Esos pagos saldrán como AMBIGUO en lugar de duplicarse silenciosamente.
    facturas_conflicto = _facturas_en_conflicto(decisiones)
    if facturas_conflicto:
        print(
            f"[matcher] Conflictos detectados: {len(facturas_conflicto)} "
            f"factura(s) disputada(s) por múltiples decisiones manuales."
        )
        for factura in sorted(facturas_conflicto):
            n = sum(
                1
                for d in decisiones.values()
                if str(d.get("accion", "")).strip().upper() == "APLICAR_FACTURA"
                and str(d.get("factura_asignada", "")).strip() == factura
            )
            print(f"          factura={factura} ({n} decisiones)")
        print(
            "          → estos pagos saldrán como AMBIGUO para que la analista reasigne."
        )

    resultados = []
    contador_decisiones = 0
    contador_ya_procesados = 0

    for idx, row in df.iterrows():
        desc = row["descripcion_norm"]
        monto = row["monto"]
        huella = generar_huella_pago(desc, monto, row["fecha"])

        # Paso 0: ya procesado en corrida anterior
        if huella in huellas_historial:
            resultados.append(
                _resultado(
                    idx,
                    row,
                    estado="YA_PROCESADO",
                    metodo_match="historial",
                    metodo_cliente="historial",
                    observacion="Pago ya conciliado en una corrida anterior. SAP es la fuente de verdad.",
                )
            )
            contador_ya_procesados += 1
            continue

        # Paso 0.5: decisión previa de la analista
        if huella in decisiones:
            previo = _aplicar_decision_previa(
                idx, row, decisiones[huella], df_cartera, facturas_conflicto
            )
            if previo is not None and previo is not DECISION_DESCARTADA:
                resultados.append(previo)
                contador_decisiones += 1
                continue
            # DECISION_DESCARTADA o AGREGAR_ALIAS → caer a cascada normal

        # Paso 1: identificar cliente
        cliente_id = _buscar_en_alias(desc, alias_map)
        metodo_cliente = "alias" if cliente_id else None

        if cliente_id is None:
            cliente_id = _buscar_cliente_en_cartera(desc, clientes_cartera)
            metodo_cliente = "directo" if cliente_id else None

        if cliente_id is None:
            resultados.append(
                _resultado(
                    idx,
                    row,
                    estado="CLIENTE_DESCONOCIDO",
                    observacion="Cliente no reconocido. Revisar si es nuevo, si falta un alias, o si es un ingreso ajeno a cartera.",
                )
            )
            continue

        facturas_cliente = df_cartera[df_cartera["cliente_norm"] == cliente_id]
        if facturas_cliente.empty:
            resultados.append(
                _resultado(
                    idx,
                    row,
                    cliente=cliente_id,
                    metodo_cliente=metodo_cliente,
                    observacion="Cliente existe pero no tiene facturas abiertas en cartera.",
                )
            )
            continue

        # Pasos 2-3-4: match exacto, acumulado, por referencia
        hits = _match_exacto(monto, facturas_cliente)
        if len(hits) == 1:
            resultados.append(
                _resultado(
                    idx,
                    row,
                    cliente=cliente_id,
                    estado="ASOCIADO",
                    metodo_match="exacto",
                    metodo_cliente=metodo_cliente,
                    facturas=hits,
                )
            )
            continue
        if len(hits) > 1:
            resultados.append(
                _resultado(
                    idx,
                    row,
                    cliente=cliente_id,
                    estado="AMBIGUO",
                    metodo_match="exacto_multiple",
                    metodo_cliente=metodo_cliente,
                    facturas=hits,
                    observacion=f"{len(hits)} facturas con el mismo valor.",
                )
            )
            continue

        combos = _match_acumulado(monto, facturas_cliente)
        if len(combos) == 1:
            resultados.append(
                _resultado(
                    idx,
                    row,
                    cliente=cliente_id,
                    estado="ASOCIADO",
                    metodo_match="acumulado",
                    metodo_cliente=metodo_cliente,
                    facturas=combos[0],
                )
            )
            continue
        if len(combos) > 1:
            resultados.append(
                _resultado(
                    idx,
                    row,
                    cliente=cliente_id,
                    estado="AMBIGUO",
                    metodo_match="acumulado_multiple",
                    metodo_cliente=metodo_cliente,
                    facturas=combos[0],
                    observacion=f"{len(combos)} combinaciones posibles.",
                )
            )
            continue

        hits_ref = _match_por_referencia(desc, facturas_cliente)
        if hits_ref:
            resultados.append(
                _resultado(
                    idx,
                    row,
                    cliente=cliente_id,
                    estado="ASOCIADO",
                    metodo_match="referencia",
                    metodo_cliente=metodo_cliente,
                    facturas=hits_ref,
                )
            )
            continue

        # Cliente existe, ninguna factura/combinación matchea
        resultados.append(
            _resultado(
                idx,
                row,
                cliente=cliente_id,
                metodo_cliente=metodo_cliente,
                observacion="Cliente identificado pero ninguna factura coincide (posible pago parcial, adelantado o factura no cargada).",
            )
        )

    df_resultado = pd.DataFrame(resultados)
    df_resultado.attrs["decisiones_previas_aplicadas"] = contador_decisiones
    df_resultado.attrs["ya_procesados"] = contador_ya_procesados
    return df_resultado
