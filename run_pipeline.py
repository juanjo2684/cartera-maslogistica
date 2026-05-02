"""Orquestador del pipeline: de datos crudos a base consolidada."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

import pandas as pd

from parser_extracto import parse_extracto
from clasificador import clasificar_movimientos
from parser_cartera import parsear_cartera
from matcher import matchear_pagos
from consolidador import consolidar
from registro_decisiones import (
    generar_huella_pago,
    huellas_ya_procesadas,
    registrar_pago_procesado,
)

# --------------------------- CONFIGURACIÓN ---------------------------
USAR_DATOS_REALES = False

if USAR_DATOS_REALES:
    EXTRACTO_PATH = "data/input/EXTRACTO_BANCARIO.csv"
    CARTERA_PATH = "data/input/Cartera_semanal_2024.xlsx"
else:
    EXTRACTO_PATH = "data/input/EXTRACTO_BANCARIO_demo.csv"
    CARTERA_PATH = "data/input/cartera_demo.xlsx"

ALIAS_PATH = "data/reference/alias_clientes.csv"
DECISIONES_PATH = "data/output/decisiones_analista.csv"
HISTORIAL_PATH = "data/output/historial_pagos.csv"

# Filtro de fechas opcional. Útil cuando la analista ya conció parte del
# extracto en SAP. Inclusivo en ambos extremos. None desactiva el filtro.
FILTRO_FECHA_DESDE: str | None = None
FILTRO_FECHA_HASTA: str | None = None

# Fecha de referencia para días vencidos y bandas. None = fecha actual.
FECHA_CORTE = "2026-04-16"
# ---------------------------------------------------------------------


def separador(titulo: str):
    print("\n" + "=" * 70)
    print(f"  {titulo}")
    print("=" * 70)


def armonizar_movimientos(df_mov: pd.DataFrame) -> pd.DataFrame:
    """Adapter: el parser produce 'valor'/'descripcion'; los siguientes esperan 'monto'/'descripcion_norm'."""
    df = df_mov.copy()
    df["monto"] = df["valor"]
    df["descripcion_norm"] = df["descripcion"]
    return df


def run():
    # -------- PASO 1 --------
    separador("PASO 1 — Parser del extracto bancario")
    df_mov = parse_extracto(
        EXTRACTO_PATH,
        fecha_desde=FILTRO_FECHA_DESDE,
        fecha_hasta=FILTRO_FECHA_HASTA,
    )
    df_mov = armonizar_movimientos(df_mov)

    descartados = df_mov.attrs.get("descartados_por_filtro", 0)
    if FILTRO_FECHA_DESDE is not None or FILTRO_FECHA_HASTA is not None:
        rango = f"desde {FILTRO_FECHA_DESDE or 'inicio'} hasta {FILTRO_FECHA_HASTA or 'fin'}"
        print(
            f"🗓️  Filtro de fechas activo ({rango}) — {descartados} movimiento(s) descartado(s)."
        )

    print(f"Movimientos leídos: {len(df_mov)}")
    if len(df_mov) == 0:
        print("⚠️  El extracto quedó vacío después del filtro. Nada que procesar.")
        return

    print(
        f"Rango de fechas: {df_mov['fecha'].min().date()} → {df_mov['fecha'].max().date()}"
    )
    print("\nMuestra:")
    print(
        df_mov[["fecha", "monto", "tipo_flujo", "descripcion"]].to_string(index=False)
    )

    # -------- PASO 2 --------
    separador("PASO 2 — Clasificador de movimientos")
    df_mov = clasificar_movimientos(df_mov)
    print("Distribución por categoría:")
    print(df_mov["categoria"].value_counts().to_string())
    print("\nMovimientos clasificados:")
    print(df_mov[["monto", "categoria", "descripcion"]].to_string(index=False))

    # -------- PASO 3 --------
    separador(f"PASO 3 — Parser de cartera (fecha_corte={FECHA_CORTE})")
    df_cart = parsear_cartera(CARTERA_PATH, fecha_corte=FECHA_CORTE)
    print(f"Facturas abiertas: {len(df_cart)}")
    print(f"Clientes únicos: {df_cart['cliente_norm'].nunique()}")
    print(f"Saldo total: ${df_cart['saldo_pendiente'].sum():,.0f} COP")
    print("\nDistribución por banda de antigüedad:")
    print(df_cart["banda_antiguedad"].value_counts().to_string())

    # -------- PASO 4 --------
    separador("PASO 4 — Motor de matching pago ↔ factura")
    pagos_cliente = df_mov[df_mov["categoria"] == "PAGO_CLIENTE"]
    print(f"Pagos de cliente a procesar: {len(pagos_cliente)}")
    df_matches = matchear_pagos(
        df_mov,
        df_cart,
        alias_path=ALIAS_PATH,
        decisiones_path=DECISIONES_PATH,
        historial_path=HISTORIAL_PATH,
    )

    ya_procesados = df_matches.attrs.get("ya_procesados", 0)
    if ya_procesados > 0:
        print(
            f"\n📋 Pagos ya procesados en corridas anteriores (omitidos): {ya_procesados}"
        )

    decisiones_aplicadas = df_matches.attrs.get("decisiones_previas_aplicadas", 0)
    if decisiones_aplicadas > 0:
        print(
            f"\n🔄 Decisiones previas de la analista aplicadas automáticamente: {decisiones_aplicadas}"
        )

    print("\nResultado del matching:")
    print(df_matches["estado_match"].value_counts().to_string())
    print("\nDetalle:")
    print(
        df_matches[
            [
                "monto",
                "cliente_identificado",
                "estado_match",
                "metodo_match",
                "facturas_asociadas",
                "observacion",
            ]
        ].to_string(index=False)
    )

    # -------- PASO 5 --------
    separador("PASO 5 — Consolidación")
    resultado = consolidar(df_cart, df_matches)
    base = resultado["base_consolidada"]
    exc = resultado["excepciones"]

    print(f"Base consolidada: {len(base)} facturas")
    print("\nDistribución por prioridad:")
    print(base["prioridad"].value_counts().to_string())
    print(f"\nFacturas con pago aplicado: {base['tiene_pago_aplicado'].sum()}")
    print(f"Excepciones pendientes de revisión humana: {len(exc)}")

    if len(exc):
        print("\n--- Excepciones por tipo ---")
        print(exc["estado_match"].value_counts().to_string())

    criticos = base[base["prioridad"] == "CRITICO"].sort_values(
        "dias_vencido", ascending=False
    )
    print("\n--- Casos críticos (vencidos > 60 días) ---")
    print(
        f"Total: {len(criticos)} facturas | ${criticos['saldo_pendiente'].sum():,.0f} COP"
    )
    if len(criticos):
        print(
            criticos[["cliente", "documento", "saldo_pendiente", "dias_vencido"]]
            .head(10)
            .to_string(index=False)
        )

    Path("data/output").mkdir(parents=True, exist_ok=True)
    base.to_csv("data/output/base_consolidada.csv", index=False)
    exc.to_csv("data/output/excepciones.csv", index=False)
    print("\n✅ Archivos escritos en data/output/")

    # -------- PASO 6: persistencia del historial --------
    # Solo entran ASOCIADOS al historial. Las excepciones quedan fuera por
    # contrato; si entraran, en la próxima corrida saldrían como YA_PROCESADO
    # y la analista no podría resolverlas nunca.
    separador("PASO 6 — Persistencia del historial de pagos")
    huellas_existentes = huellas_ya_procesadas(Path(HISTORIAL_PATH))
    asociados = df_matches[df_matches["estado_match"] == "ASOCIADO"]

    # Replicamos el filtro del matcher: id_pago es índice posicional sobre
    # el subset de PAGO_CLIENTE, no sobre df_mov. Sin esto, df_mov.iloc[id_pago]
    # devolvería un movimiento equivocado.
    df_pagos_cliente = (
        df_mov[df_mov["categoria"] == "PAGO_CLIENTE"].copy().reset_index(drop=True)
    )

    nuevos = 0
    duplicados_omitidos = 0
    for _, fila in asociados.iterrows():
        pago_origen = df_pagos_cliente.iloc[fila["id_pago"]]
        huella = generar_huella_pago(
            pago_origen["descripcion_norm"],
            pago_origen["monto"],
            pago_origen["fecha"],
        )

        if huella in huellas_existentes:
            duplicados_omitidos += 1
            continue

        registrar_pago_procesado(
            huella_pago=huella,
            fecha_pago=pago_origen["fecha"],
            monto=pago_origen["monto"],
            descripcion_pago=pago_origen["descripcion"],
            estado_match_inicial=fila["estado_match"],
            metodo_match=fila["metodo_match"],
            facturas_asociadas=fila["facturas_asociadas"],
            ruta=Path(HISTORIAL_PATH),
        )
        nuevos += 1

    print(
        f"Historial actualizado: {nuevos} nuevos pagos registrados ({duplicados_omitidos} ya estaban)."
    )


if __name__ == "__main__":
    run()
