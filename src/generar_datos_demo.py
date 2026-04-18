"""
Generador de datos sintéticos para demostración del MVP.

Contexto:
    Los datos reales de +logística están bajo NDA y la cartera SAP
    viene anonimizada. Para la demostración del MVP se generan datos
    sintéticos que replican la estructura real y cubren todos los
    escenarios de negocio que la solución debe resolver.

Archivos generados:
    - EXTRACTO_BANCARIO.csv  → extracto plano del banco (formato Bancolombia)
    - cartera_demo.xlsx      → cartera con nombres reales y facturas pendientes

Escenarios cubiertos:
    1. Match exacto:     pago coincide con 1 sola factura
    2. Match acumulado:  pago = suma de varias facturas del cliente
    3. Ambiguo:          pago coincide con más de una factura individual
    4. No identificado:  pagador no existe en la cartera
    5. Pago parcial:     monto menor a cualquier factura del cliente
    6. Cliente sin pago: cartera vencida sin actividad bancaria
    7. Ruido:            egresos, comisiones, intereses que deben filtrarse

Uso:
    python generar_datos_demo.py
    → Genera los archivos en data/input/
"""

from __future__ import annotations
from pathlib import Path
from datetime import datetime, timedelta
import csv

import pandas as pd
import numpy as np


# =====================================================================
# CONFIGURACIÓN
# =====================================================================

# Fecha de referencia para la demo (simula "hoy").
FECHA_REF = datetime(2026, 4, 16)
FECHA_EXTRACTO = datetime(2026, 4, 15)  # Los movimientos son del día anterior.
CUENTA_BANCARIA = "542-727683-26"
SUCURSAL = 245


# =====================================================================
# DATOS SINTÉTICOS — CARTERA
# =====================================================================

CLIENTES_FACTURAS = [
    # --- CLIENTE 1: Match exacto ---
    # Pago de $7,051,557 coincide exacto con FV-1010.
    {
        "nombre": "ALMACENES GLOBALES SA",
        "facturas": [
            {"num": "FV-1010", "valor": 7051557,  "dias_venc": 10},
            {"num": "FV-1011", "valor": 3800000,  "dias_venc": 45},
        ],
    },
    # --- CLIENTE 2: Match acumulado (2 facturas) ---
    # Pago de $3,500,000 = FV-1002 ($2,300,000) + FV-1003 ($1,200,000).
    {
        "nombre": "TRANSPORTES DEL NORTE SAS",
        "facturas": [
            {"num": "FV-1001", "valor": 4500000,  "dias_venc": 5},
            {"num": "FV-1002", "valor": 2300000,  "dias_venc": 25},
            {"num": "FV-1003", "valor": 1200000,  "dias_venc": 25},
        ],
    },
    # --- CLIENTE 3: Match acumulado (2 facturas) ---
    # Pago de $8,000,000 = FV-1020 ($5,000,000) + FV-1021 ($3,000,000).
    {
        "nombre": "COMERCIALIZADORA PACIFIC SAS",
        "facturas": [
            {"num": "FV-1020", "valor": 5000000,  "dias_venc": 8},
            {"num": "FV-1021", "valor": 3000000,  "dias_venc": 8},
            {"num": "FV-1022", "valor": 2000000,  "dias_venc": 35},
        ],
    },
    # --- CLIENTE 4: Ambiguo ---
    # Pago de $1,500,000 = FV-1040 ($1,500,000) O FV-1041 ($1,500,000).
    # Ambas facturas tienen el mismo monto → no se puede decidir automáticamente.
    {
        "nombre": "LOGISTICA INTEGRADA CO SAS",
        "facturas": [
            {"num": "FV-1040", "valor": 1500000,  "dias_venc": 15},
            {"num": "FV-1041", "valor": 1500000,  "dias_venc": 20},
        ],
    },
    # --- CLIENTE 5: Pago parcial ---
    # Pago de $1,500,000 pero la factura es de $2,800,000.
    # No coincide exacto ni acumulado → queda para revisión.
    {
        "nombre": "QUIMICOS ANDINOS SAS",
        "facturas": [
            {"num": "FV-1070", "valor": 2800000,  "dias_venc": 55},
        ],
    },
    # --- CLIENTE 6: Cartera crítica sin pago ---
    # Tiene facturas muy vencidas pero no aparece ningún pago en el extracto.
    {
        "nombre": "INDUSTRIAS METALICAS DEL SUR SAS",
        "facturas": [
            {"num": "FV-1030", "valor": 12500000, "dias_venc": 70},
            {"num": "FV-1031", "valor": 8900000,  "dias_venc": 130},
        ],
    },
    # --- CLIENTE 7: Cartera al día sin pago ---
    # Facturas que aún no vencen. Sin urgencia pero útil para el dashboard.
    {
        "nombre": "EMPAQUES Y SOLUCIONES SAS",
        "facturas": [
            {"num": "FV-1050", "valor": 6200000,  "dias_venc": -5},
            {"num": "FV-1051", "valor": 4100000,  "dias_venc": -10},
        ],
    },
    # --- CLIENTE 8: Cartera vencida 91-120 sin pago ---
    {
        "nombre": "DISTRIBUIDORA CENTRAL LTDA",
        "facturas": [
            {"num": "FV-1060", "valor": 9500000,  "dias_venc": 95},
            {"num": "FV-1061", "valor": 3200000,  "dias_venc": 40},
        ],
    },
]


# =====================================================================
# DATOS SINTÉTICOS — EXTRACTO BANCARIO
# =====================================================================

MOVIMIENTOS_BANCO = [
    # --- ABONOS (pagos de clientes) ---
    # 1. Match exacto con FV-1010 de ALMACENES GLOBALES
    {"valor":  7051557.00, "codigo": 2504, "desc": "PAGO DE PROV ALMACENES GLOBALE"},
    # 2. Match acumulado con FV-1002 + FV-1003 de TRANSPORTES DEL NORTE
    {"valor":  3500000.00, "codigo": 8142, "desc": "PAGO INTERBANC TRANSPORTES DEL"},
    # 3. Match acumulado con FV-1020 + FV-1021 de COMERCIALIZADORA PACIFIC
    {"valor":  8000000.00, "codigo": 2504, "desc": "PAGO DE PROV COMERCIALIZADORA"},
    # 4. Ambiguo: coincide con FV-1040 y FV-1041 de LOGISTICA INTEGRADA
    {"valor":  1500000.00, "codigo": 2504, "desc": "PAGO DE PROV LOGISTICA INTEGRA"},
    # 5. No identificado: TEXTILES MODERNOS no está en la cartera
    {"valor":  4200000.00, "codigo": 2504, "desc": "PAGO DE PROV TEXTILES MODERNOS"},
    # 6. Pago parcial: QUIMICOS ANDINOS paga menos de lo que debe
    {"valor":  1500000.00, "codigo": 8142, "desc": "PAGO INTERBANC QUIMICOS ANDINO"},

    # --- CARGOS (egresos — deben ser filtrados por el clasificador) ---
    {"valor": -2750081.00, "codigo": 8162, "desc": "PAGO A PROVE GRUPO LOGITRANS"},
    {"valor":  -748800.00, "codigo": 8162, "desc": "PAGO A PROVE JORGE ANDRES US"},
    {"valor": -5644980.00, "codigo": 8162, "desc": "PAGO A PROVE VQ CONTAINERS S"},
    {"valor":  -113199.00, "codigo": 1160, "desc": "PAGO A PROV CARLOS ANDRES MONT"},
    {"valor":-1236094.82,  "codigo": 1319, "desc": "DEBITO POR ABONO CARTERA"},

    # --- OTROS (ruido que debe clasificarse correctamente) ---
    {"valor":      4.71,   "codigo": 2999, "desc": "ABONO INTERESES AHORROS"},
    {"valor":  -85000.00,  "codigo": 7371, "desc": "COMISION PAGO A PROVEEDORES"},
    {"valor":  -32000.00,  "codigo": 3339, "desc": "IMPTO GOBIERNO 4X1000"},
]


# =====================================================================
# GENERACIÓN DE ARCHIVOS
# =====================================================================

def generar_extracto_csv(ruta_salida: Path) -> None:
    """
    Genera el extracto bancario sintético en formato CSV plano
    (sin encabezados, 10 columnas, idéntico al formato real de Bancolombia).
    """
    fecha_str = FECHA_EXTRACTO.strftime("%Y%m%d")

    with open(ruta_salida, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for mov in MOVIMIENTOS_BANCO:
            # Formato: cuenta, sucursal, vacío, fecha, vacío, valor, código, desc, 0, vacío
            writer.writerow([
                CUENTA_BANCARIA,
                f" {SUCURSAL}",
                " ",
                f" {fecha_str}",
                "",
                f" {mov['valor']}",
                f" {mov['codigo']}",
                f" {mov['desc']}",
                f" 0",
                "",
            ])

    print(f"  ✅ Extracto generado: {ruta_salida} ({len(MOVIMIENTOS_BANCO)} movimientos)")


def generar_cartera_xlsx(ruta_salida: Path) -> None:
    """
    Genera la cartera sintética en formato XLSX,
    replicando la estructura de la cartera semanal de +logística.
    
    Estructura:
        - Fila 0: título de la hoja (se ignora al parsear).
        - Fila 1: encabezados.
        - Fila 2+: datos de facturas.
    """
    filas = []
    for cliente in CLIENTES_FACTURAS:
        for factura in cliente["facturas"]:
            fecha_venc = FECHA_REF - timedelta(days=factura["dias_venc"])
            # La fecha de contabilización es ~30 días antes del vencimiento.
            fecha_cont = fecha_venc - timedelta(days=30)

            filas.append({
                "Nombre SN": cliente["nombre"],
                "Nº documento": factura["num"],
                "Fecha de contabilización": fecha_cont.strftime("%d/%m/%Y"),
                "Fecha de vencimiento": fecha_venc.strftime("%d/%m/%Y"),
                "Importe original": factura["valor"],
                "Saldo vencido": factura["valor"],  # Sin pagos parciales en el setup
                "Abono futuro": None,
            })

    df = pd.DataFrame(filas)

    # Ajustar las facturas con "pago parcial" previo para demostrar ese escenario.
    # TECNAS (FV-1001): el importe original era $4,500,000 pero queda $4,500,000 (no hay parcial ahí).
    # Lo dejamos limpio — el pago parcial se demuestra con QUIMICOS ANDINOS donde
    # el pago de $1,500,000 no coincide con la factura de $2,800,000.

    # Escribir con formato semanal (título en fila 0, headers en fila 1).
    with pd.ExcelWriter(ruta_salida, engine="openpyxl") as writer:
        # Crear hoja con título
        titulo_df = pd.DataFrame(
            [[None] * len(df.columns)],
            columns=df.columns,
        )
        # Poner título en la primera celda
        titulo_df.iloc[0, 0] = None  # se maneja abajo

        # Escribir datos sin header de pandas (lo ponemos manual)
        df.to_excel(writer, sheet_name="16ABR", index=False, startrow=2, header=False)
        ws = writer.sheets["16ABR"]

        # Fila 1: título de la hoja
        ws.cell(row=1, column=5, value=f"estado de cuenta {FECHA_REF.strftime('%d %b %Y')}")

        # Fila 2: encabezados
        for col_idx, col_name in enumerate(df.columns, 1):
            ws.cell(row=2, column=col_idx, value=col_name)

    num_facturas = len(filas)
    num_clientes = len(CLIENTES_FACTURAS)
    saldo_total = sum(f["valor"] for c in CLIENTES_FACTURAS for f in c["facturas"])
    print(f"  ✅ Cartera generada: {ruta_salida}")
    print(f"     {num_facturas} facturas, {num_clientes} clientes, "
          f"saldo total ${saldo_total:,.0f}")


# =====================================================================
# MAIN
# =====================================================================

def main():
    """Genera todos los archivos sintéticos en data/input/."""
    base = Path(__file__).parent.parent / "data" / "input"
    base.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 60)
    print("GENERANDO DATOS SINTÉTICOS PARA DEMO")
    print("=" * 60)
    print(f"  Fecha de referencia: {FECHA_REF.strftime('%Y-%m-%d')}")
    print(f"  Fecha del extracto:  {FECHA_EXTRACTO.strftime('%Y-%m-%d')}\n")

    generar_extracto_csv(base / "EXTRACTO_BANCARIO.csv")
    generar_cartera_xlsx(base / "cartera_demo.xlsx")

    print("\n" + "=" * 60)
    print("ESCENARIOS INCLUIDOS EN LA DEMO")
    print("=" * 60)
    escenarios = [
        ("Match exacto",      "ALMACENES GLOBALES paga $7,051,557 = FV-1010"),
        ("Match acumulado",   "TRANSPORTES DEL NORTE paga $3,500,000 = FV-1002 + FV-1003"),
        ("Match acumulado",   "PACIFIC paga $8,000,000 = FV-1020 + FV-1021"),
        ("Ambiguo",           "LOGISTICA INTEGRADA paga $1,500,000 → FV-1040 o FV-1041"),
        ("No identificado",   "TEXTILES MODERNOS ($4,200,000) no está en cartera"),
        ("Pago parcial",      "QUIMICOS ANDINOS paga $1,500,000 < deuda $2,800,000"),
        ("Sin pago (crítico)","METALICAS DEL SUR: $21.4M vencidos 61-130 días"),
        ("Sin pago (al día)", "EMPAQUES Y SOLUCIONES: $10.3M por vencer"),
        ("Sin pago (grave)",  "DISTRIBUIDORA CENTRAL: $9.5M vencidos 95 días"),
        ("Ruido filtrado",    "5 egresos + 1 interés + 2 gastos bancarios"),
    ]
    for i, (tipo, desc) in enumerate(escenarios, 1):
        print(f"  {i:>2d}. [{tipo:<18s}] {desc}")

    print("\n  Archivos listos en:", base)
    print()


if __name__ == "__main__":
    main()
