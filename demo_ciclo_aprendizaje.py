"""Demo del ciclo de aprendizaje del sistema de cartera.

Ejecuta tres corridas del matcher con datos sintéticos en memoria,
demostrando dos comportamientos clave del MVP:
  1. Aprendizaje: una decisión registrada por la analista se reaplica
     automáticamente en corridas siguientes.
  2. Validación defensiva: una decisión histórica que apunta a una factura
     ya inexistente se descarta y el pago vuelve a la cascada normal.

El demo es autocontenido: usa archivos temporales para decisiones,
historial y catálogo de alias. No toca data/output/ del repo real.

Uso:
    python demo_ciclo_aprendizaje.py             # corre todo seguido
    python demo_ciclo_aprendizaje.py --pausas    # se detiene entre secciones
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd

from matcher import matchear_pagos
from registro_decisiones import (
    agregar_alias,
    cargar_decisiones,
    generar_huella_pago,
    registrar_decision,
)

# Nombre del cliente y alias del demo. Importante: ningún token de 4+
# caracteres del nombre del cliente debe aparecer en la descripción del
# pago, para que el matcher NO pueda resolverlo sin el alias en la
# corrida 1. Esto es lo que justifica que la analista intervenga.
CLIENTE_DEMO = "LOGISTICA TRANSPORTES SOLANO SAS"
DESC_PAGO_ENIGMATICO = "TRANSFER ALFA REF 8821"
ALIAS_DEMO = "TRANSFER ALFA"


# -----------------------------------------------------------------------------
# Utilidades de presentación
# -----------------------------------------------------------------------------


def seccion(titulo: str, char: str = "="):
    print()
    print(char * 70)
    print(f"  {titulo}")
    print(char * 70)


def subseccion(titulo: str):
    print()
    print(f"--- {titulo} ---")


def pausa(activa: bool, mensaje: str = "Presiona Enter para continuar..."):
    if activa:
        try:
            input(f"\n  {mensaje}")
        except (KeyboardInterrupt, EOFError):
            print("\nDemo interrumpido.")
            sys.exit(0)


def formato_cop(valor: float) -> str:
    return f"${valor:,.0f}"


def imprimir_resultado_matcher(df: pd.DataFrame):
    """Renderiza el DataFrame de resultados de matchear_pagos en consola."""
    if df.empty:
        print("  (sin pagos a procesar)")
        return
    cols = [
        "id_pago",
        "monto",
        "estado_match",
        "metodo_match",
        "cliente_identificado",
        "facturas_asociadas",
    ]
    df_vista = df[cols].copy()
    df_vista["monto"] = df_vista["monto"].apply(formato_cop)
    print(df_vista.to_string(index=False))


# -----------------------------------------------------------------------------
# Datos del escenario
# -----------------------------------------------------------------------------


def construir_cartera_inicial() -> pd.DataFrame:
    """Cartera con dos facturas vigentes para el cliente del demo."""
    return pd.DataFrame(
        [
            {
                "cliente": CLIENTE_DEMO,
                "cliente_norm": CLIENTE_DEMO,
                "documento": "F-001",
                "saldo_pendiente": 1_000_000.0,
            },
            {
                "cliente": CLIENTE_DEMO,
                "cliente_norm": CLIENTE_DEMO,
                "documento": "F-002",
                "saldo_pendiente": 2_000_000.0,
            },
        ]
    )


def construir_cartera_post_conciliacion() -> pd.DataFrame:
    """Cartera del escenario alterno: F-001 ya fue conciliada en SAP."""
    return pd.DataFrame(
        [
            {
                "cliente": CLIENTE_DEMO,
                "cliente_norm": CLIENTE_DEMO,
                "documento": "F-002",
                "saldo_pendiente": 2_000_000.0,
            },
        ]
    )


def construir_pagos() -> pd.DataFrame:
    """Dos pagos:
    - Pago 0: descripción NO contiene tokens del nombre del cliente.
              Sin alias registrado, el matcher no lo identifica.
    - Pago 1: descripción contiene el nombre del cliente. Match limpio.
    """
    return pd.DataFrame(
        [
            {
                "fecha": pd.Timestamp("2026-04-15"),
                "monto": 1_000_000.0,
                "descripcion": DESC_PAGO_ENIGMATICO,
                "descripcion_norm": DESC_PAGO_ENIGMATICO,
                "categoria": "PAGO_CLIENTE",
            },
            {
                "fecha": pd.Timestamp("2026-04-15"),
                "monto": 2_000_000.0,
                "descripcion": f"PAGO DE PROV {CLIENTE_DEMO} REF 9912",
                "descripcion_norm": f"PAGO DE PROV {CLIENTE_DEMO} REF 9912",
                "categoria": "PAGO_CLIENTE",
            },
        ]
    )


# -----------------------------------------------------------------------------
# Ejecución del demo
# -----------------------------------------------------------------------------


def correr_demo(con_pausas: bool):
    seccion("DEMO — Ciclo de aprendizaje del sistema de cartera +logística")

    print(f"""
  Este demo ejecuta tres corridas del matcher con datos sintéticos en
  memoria, mostrando cómo el sistema APRENDE de las decisiones de la
  analista y cómo se PROTEGE de aplicar decisiones obsoletas.

  Datos del escenario:
    Cartera (cliente: {CLIENTE_DEMO}):
      F-001  →  $1.000.000
      F-002  →  $2.000.000

    Pagos del extracto bancario:
      Pago 0:  $1.000.000  "{DESC_PAGO_ENIGMATICO}"
               (la descripción NO contiene el nombre del cliente;
                el sistema no lo puede identificar sin un alias)

      Pago 1:  $2.000.000  "PAGO DE PROV {CLIENTE_DEMO}..."
               (la descripción sí contiene el nombre y matchea exactamente
                el saldo de F-002 — el sistema lo resuelve solo)
""")
    pausa(con_pausas)

    # Workspace efímero: decisiones, historial y alias viven aquí.
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ruta_decisiones = tmp / "decisiones_analista.csv"
        ruta_historial = tmp / "historial_pagos.csv"
        ruta_alias = tmp / "alias_clientes.csv"

        # Inicializar archivos vacíos para que el matcher no falle.
        pd.DataFrame(
            columns=[
                "fecha_corrida",
                "huella_pago",
                "fecha_pago",
                "monto",
                "descripcion_pago",
                "estado_match_inicial",
                "metodo_match",
                "facturas_asociadas",
            ]
        ).to_csv(ruta_historial, index=False)

        df_pagos = construir_pagos()
        df_cartera = construir_cartera_inicial()

        # =====================================================================
        # CORRIDA 1 — Sistema sin memoria
        # =====================================================================
        seccion("CORRIDA 1 — Sistema sin memoria", char="-")
        print("""
  El matcher procesa los dos pagos sin ninguna decisión previa registrada
  ni alias en el catálogo.
""")

        df_r1 = matchear_pagos(
            df_pagos=df_pagos,
            df_cartera=df_cartera,
            alias_path=ruta_alias,
            decisiones_path=ruta_decisiones,
            historial_path=ruta_historial,
        )

        subseccion("Resultado")
        imprimir_resultado_matcher(df_r1)

        excepciones = (df_r1["estado_match"] != "ASOCIADO").sum()
        print(f"\n  → Excepciones a resolver: {excepciones}")
        print(
            f"  → Pagos resueltos automáticamente: {(df_r1['estado_match'] == 'ASOCIADO').sum()}"
        )

        pausa(con_pausas)

        # =====================================================================
        # INTERVENCIÓN — La analista decide
        # =====================================================================
        seccion("INTERVENCIÓN MANUAL — La analista decide", char="-")
        print(f"""
  La analista abre el dashboard y resuelve la excepción del Pago 0:
    "El nombre '{ALIAS_DEMO}' corresponde a {CLIENTE_DEMO}.
     Voy a registrar este alias para que el sistema lo aprenda."

  → Acción: AGREGAR_ALIAS
  → Alias origen:  "{ALIAS_DEMO}"
  → Cliente real:  "{CLIENTE_DEMO}"
""")

        # 1. Registrar la decisión en el archivo de decisiones (auditoría).
        pago_0 = df_pagos.iloc[0]
        huella_0 = generar_huella_pago(
            pago_0["descripcion_norm"], pago_0["monto"], pago_0["fecha"]
        )
        registrar_decision(
            huella_pago=huella_0,
            id_pago_origen=0,
            monto=float(pago_0["monto"]),
            descripcion_pago=pago_0["descripcion"],
            accion="AGREGAR_ALIAS",
            cliente_asignado=CLIENTE_DEMO,
            alias_origen=ALIAS_DEMO,
            comentario="Demo: alias aprendido en la sesión.",
            usuario="demo",
            ruta=ruta_decisiones,
        )

        # 2. Agregar el alias al catálogo (igual que hace el dashboard).
        agregar_alias(
            alias=ALIAS_DEMO,
            cliente_real=CLIENTE_DEMO,
            notas="Demo: alias agregado durante la sesión.",
            ruta=ruta_alias,
        )

        print("  ✓ Decisión registrada en decisiones_analista.csv")
        print("  ✓ Alias agregado al catálogo alias_clientes.csv")

        pausa(con_pausas)

        # =====================================================================
        # ESTADO DEL CEREBRO — qué quedó persistido
        # =====================================================================
        seccion("ESTADO DEL 'CEREBRO' DEL SISTEMA", char="-")
        print("""
  Después de la intervención, el sistema tiene memoria persistida.
  Esto es lo que se aplicará en la próxima corrida.
""")

        subseccion("Decisiones registradas")
        df_dec = cargar_decisiones(ruta_decisiones)
        cols_dec = [
            "fecha_decision",
            "accion",
            "cliente_asignado",
            "alias_origen",
            "estado_decision",
        ]
        print(df_dec[cols_dec].to_string(index=False))

        subseccion("Catálogo de alias")
        df_alias = pd.read_csv(ruta_alias, comment="#")
        print(df_alias.to_string(index=False))

        pausa(con_pausas)

        # =====================================================================
        # CORRIDA 2 — Sistema con memoria
        # =====================================================================
        seccion("CORRIDA 2 — Sistema con memoria", char="-")
        print("""
  El matcher procesa los MISMOS pagos sobre la MISMA cartera, pero ahora
  con el alias aprendido y la decisión registrada.
""")

        df_r2 = matchear_pagos(
            df_pagos=df_pagos,
            df_cartera=df_cartera,
            alias_path=ruta_alias,
            decisiones_path=ruta_decisiones,
            historial_path=ruta_historial,
        )

        subseccion("Resultado")
        imprimir_resultado_matcher(df_r2)

        excepciones = (df_r2["estado_match"] != "ASOCIADO").sum()
        asociados = (df_r2["estado_match"] == "ASOCIADO").sum()
        print(f"\n  → Excepciones a resolver: {excepciones}")
        print(f"  → Pagos resueltos automáticamente: {asociados}")
        print("\n  💡 El Pago 0 ya no aparece como CLIENTE_DESCONOCIDO.")
        print(f"     El alias '{ALIAS_DEMO}' se aplicó automáticamente y la")
        print("     cascada normal lo resolvió contra F-001 por match exacto.")

        pausa(con_pausas)

        # =====================================================================
        # ESCENARIO ALTERNO — Validación defensiva
        # =====================================================================
        seccion("ESCENARIO ALTERNO — Validación defensiva", char="-")
        print("""
  Imagina que entre la corrida 2 y hoy, SAP concilió F-001 directamente
  (la analista la marcó pagada manualmente, o la fusionaron con otra
  factura). En la cartera nueva, F-001 YA NO EXISTE.

  Para forzar el caso, registramos una decisión APLICAR_FACTURA → F-001
  sobre el Pago 0. Como F-001 ya no está en cartera, esta decisión es
  inválida — el sistema debe descartarla.
""")

        # Registrar una decisión obsoleta sobre Pago 0.
        registrar_decision(
            huella_pago=huella_0,
            id_pago_origen=0,
            monto=float(pago_0["monto"]),
            descripcion_pago=pago_0["descripcion"],
            accion="APLICAR_FACTURA",
            factura_asignada="F-001",
            cliente_asignado=CLIENTE_DEMO,
            comentario="Demo: decisión que quedará obsoleta.",
            usuario="demo",
            ruta=ruta_decisiones,
        )

        df_cartera_post = construir_cartera_post_conciliacion()
        print("  Cartera actualizada (F-001 fue conciliada y removida):")
        print(
            df_cartera_post[["documento", "cliente", "saldo_pendiente"]].to_string(
                index=False
            )
        )

        pausa(con_pausas)

        seccion("CORRIDA 3 — Validación defensiva en acción", char="-")
        print()

        df_r3 = matchear_pagos(
            df_pagos=df_pagos,
            df_cartera=df_cartera_post,
            alias_path=ruta_alias,
            decisiones_path=ruta_decisiones,
            historial_path=ruta_historial,
        )

        subseccion("Resultado")
        imprimir_resultado_matcher(df_r3)

        print(
            "\n  💡 La decisión APLICAR_FACTURA → F-001 fue DESCARTADA por el matcher"
        )
        print(
            "     (ver el log [matcher] arriba). El Pago 0 volvió a la cascada normal,"
        )
        print("     que esta vez no encontró match exacto (F-001 ya no existe).")
        print("     El sistema escala de vuelta a la analista en lugar de aplicar")
        print("     una decisión basada en datos obsoletos.")

        pausa(con_pausas)

        # =====================================================================
        # CIERRE
        # =====================================================================
        seccion("CIERRE — ¿Qué demostró este demo?")
        print("""
  ✅ APRENDIZAJE
     Una decisión registrada por la analista se reaplica automáticamente
     en corridas siguientes. El sistema reduce el trabajo manual con cada
     decisión que se le enseña.

  ✅ AUTOPROTECCIÓN
     Las decisiones históricas no se aplican ciegamente. El matcher valida
     que las facturas referenciadas sigan vigentes en la cartera actual,
     y descarta decisiones obsoletas escalándolas de vuelta a la analista.

  📊 Para ver este flujo en vivo sobre el dashboard:
     1. Cierra este demo.
     2. Corre  python run_pipeline.py
     3. Abre   streamlit run app/streamlit_app.py
     4. Visita la vista 'Decisiones registradas' para ver el cerebro persistido.
""")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Demo del ciclo de aprendizaje del sistema de cartera.",
    )
    parser.add_argument(
        "--pausas",
        action="store_true",
        help="Pausa entre secciones esperando Enter (modo presentación).",
    )
    args = parser.parse_args()

    try:
        correr_demo(con_pausas=args.pausas)
        return 0
    except KeyboardInterrupt:
        print("\n\nDemo interrumpido.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
