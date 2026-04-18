"""
Orquestador del pipeline completo: de datos crudos a base consolidada.

Ejecuta los 5 pasos en orden e imprime un resumen por cada uno.

Notas de diseño:
    - Este script actúa como ADAPTER entre parser_extracto (que produce
      columnas 'valor'/'descripcion') y los módulos siguientes (que esperan
      'monto'/'descripcion_norm'). La armonización se hace en run(), no en
      los módulos de src/, para no tocar código ya probado.
    - Usa os.chdir(ROOT) para que las rutas relativas funcionen sin importar
      desde qué carpeta se ejecute el script.
"""

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


# --------------------------- CONFIGURACIÓN ---------------------------
# Interruptor simple: True usa datos reales (NDA), False usa datos demo.
# Los datos reales deben estar en data/input/ con los nombres canónicos.
USAR_DATOS_REALES = False

if USAR_DATOS_REALES:
    EXTRACTO_PATH = "data/input/EXTRACTO_BANCARIO.csv"
    CARTERA_PATH = "data/input/Cartera_semanal_2024.xlsx"
else:
    EXTRACTO_PATH = "data/input/EXTRACTO_BANCARIO_demo.csv"
    CARTERA_PATH = "data/input/cartera_demo.xlsx"

ALIAS_PATH = "data/reference/alias_clientes.csv"
DECISIONES_PATH = "data/output/decisiones_analista.csv"

# Fecha de referencia para calcular días vencidos y bandas de antigüedad.
# Con 2026-04-16 las bandas se pueblan de forma realista sobre los datos
# demo (que tienen facturas a distintas edades). Cambiar a None para usar
# la fecha del sistema.
FECHA_CORTE = "2026-04-16"
# ---------------------------------------------------------------------


def separador(titulo: str):
    print("\n" + "=" * 70)
    print(f"  {titulo}")
    print("=" * 70)


def armonizar_movimientos(df_mov: pd.DataFrame) -> pd.DataFrame:
    """
    Adapter entre parser_extracto y los módulos posteriores.

    El parser produce:  valor, descripcion
    Los siguientes esperan: monto, descripcion_norm

    Aquí añadimos esas columnas sin alterar las originales.
    """
    df = df_mov.copy()
    df["monto"] = df["valor"]
    df["descripcion_norm"] = df["descripcion"]  # ya viene en upper + strip
    return df


def run():
    # --- PASO 1 ---
    separador("PASO 1 — Parser del extracto bancario")
    df_mov = parse_extracto(EXTRACTO_PATH)
    df_mov = armonizar_movimientos(df_mov)
    print(f"Movimientos leídos: {len(df_mov)}")
    print(
        f"Rango de fechas: {df_mov['fecha'].min().date()} → {df_mov['fecha'].max().date()}"
    )
    print("\nMuestra:")
    print(
        df_mov[["fecha", "monto", "tipo_flujo", "descripcion"]].to_string(index=False)
    )

    # --- PASO 2 ---
    separador("PASO 2 — Clasificador de movimientos")
    df_mov = clasificar_movimientos(df_mov)
    print("Distribución por categoría:")
    print(df_mov["categoria"].value_counts().to_string())
    print("\nMovimientos clasificados:")
    print(df_mov[["monto", "categoria", "descripcion"]].to_string(index=False))

    # --- PASO 3 ---
    separador(f"PASO 3 — Parser de cartera (fecha_corte={FECHA_CORTE})")
    df_cart = parsear_cartera(CARTERA_PATH, fecha_corte=FECHA_CORTE)
    print(f"Facturas abiertas: {len(df_cart)}")
    print(f"Clientes únicos: {df_cart['cliente_norm'].nunique()}")
    print(f"Saldo total: ${df_cart['saldo_pendiente'].sum():,.0f} COP")
    print("\nDistribución por banda de antigüedad:")
    print(df_cart["banda_antiguedad"].value_counts().to_string())

    # --- PASO 4 ---
    separador("PASO 4 — Motor de matching pago ↔ factura")
    pagos_cliente = df_mov[df_mov["categoria"] == "PAGO_CLIENTE"]
    print(f"Pagos de cliente a procesar: {len(pagos_cliente)}")
    df_matches = matchear_pagos(
        df_mov, df_cart, alias_path=ALIAS_PATH, decisiones_path=DECISIONES_PATH
    )

    # Reporte de trazabilidad: cuántos pagos se resolvieron con decisión previa.
    decisiones_aplicadas = df_matches.attrs.get("decisiones_previas_aplicadas", 0)
    if decisiones_aplicadas > 0:
        print(
            f"\n🔄 Decisiones previas de la analista aplicadas automáticamente: "
            f"{decisiones_aplicadas}"
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

    # --- PASO 5 ---
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

    # Guardar salidas
    Path("data/output").mkdir(parents=True, exist_ok=True)
    base.to_csv("data/output/base_consolidada.csv", index=False)
    exc.to_csv("data/output/excepciones.csv", index=False)
    print("\n✅ Archivos escritos en data/output/")


if __name__ == "__main__":
    run()
