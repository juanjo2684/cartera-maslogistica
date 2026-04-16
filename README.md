# Automatización de Gestión de Cartera — +logística

> **Reto 10 · Programa Beca SER ANDI — Inteligencia Artificial**
> Operado por NODO / Universidad EAFIT · Abril 2026

MVP académico para automatizar el proceso semanal de gestión de cartera de +logística: cruzar los movimientos del extracto bancario con el estado de cuenta de SAP, identificar pagos, clasificar cartera por antigüedad y priorizar el seguimiento a clientes.

---

## 📌 Estado del proyecto

| Fase | Estado |
|---|---|
| Entendimiento (AS-IS) | ✅ Completado |
| Diseño TO-BE | ✅ Completado |
| Automatización (MVP) | 🚧 En curso |
| Monitoreo y presentación | ⏳ Pendiente |

Avance actual: **Paso 1 de 6** — Parser del extracto bancario.

---

## 📁 Estructura del repositorio

```
cartera_maslogistica/
├── data/
│   ├── input/        # Archivos que carga la operadora (NO versionados por NDA)
│   ├── reference/    # Datos de referencia fijos (catálogos, reglas)
│   └── output/       # Base consolidada y reportes generados
├── src/              # Código fuente (módulos de procesamiento)
│   ├── parser_extracto.py
│   ├── clasificador.py     (próximo)
│   ├── parser_cartera.py   (próximo)
│   ├── matcher.py          (próximo)
│   └── consolidador.py     (próximo)
├── notebooks/        # Exploración y pruebas paso a paso
├── app/              # Interfaz Streamlit para la operadora final
├── tests/            # Pruebas unitarias
├── requirements.txt
├── .gitignore
└── README.md
```

---

## 🚀 Instalación y ejecución

### Requisitos previos
- Python 3.10 o superior
- Git

### 1. Clonar el repositorio
```bash
git clone https://github.com/<tu-usuario>/cartera_maslogistica.git
cd cartera_maslogistica
```

### 2. Crear entorno virtual e instalar dependencias

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Colocar los archivos de entrada
Los datos de +logística están bajo NDA y **no se incluyen en el repositorio**. Debes colocar manualmente en `data/input/`:

- `EXTRACTO_BANCARIO.csv` — exportación plana del banco (10 columnas sin encabezado).
- `carteracruda_de_sap.xlsx` — exportación del módulo de cartera de SAP Business One.

### 4. Ejecutar el parser (validación rápida)
```bash
python -m src.parser_extracto
```

Debe imprimir el resumen del extracto: filas parseadas, rango de fechas y conteo de abonos/cargos.

---

## 🧩 Datos utilizados

| Archivo | Origen | Uso |
|---|---|---|
| `EXTRACTO_BANCARIO.csv` | Bancolombia CTE (exportación diaria) | Insumo operacional principal |
| `carteracruda_de_sap.xlsx` | SAP Business One — módulo Cartera | Insumo operacional principal |
| `Mvto_BANCOLOMBIA_CTE_2024.xlsx` | Histórico clasificado manualmente | Solo referencia para construir reglas |
| `Cartera_semanal_2024.xlsx` | Histórico de gestión semanal | Solo referencia y validación |

---

## 🎯 Alcance del MVP

**Dentro del alcance:**
- Carga manual de archivos (extracto + cartera).
- Clasificación automática de movimientos bancarios por reglas deterministas.
- Matching de pagos con facturas por valor exacto, acumulado y referencia.
- Base consolidada con trazabilidad.
- Dashboard de priorización (Streamlit).

**Fuera del alcance:**
- Integración directa con SAP o portal bancario.
- Envío automático de correos de seguimiento.
- Procesamiento de soportes de pago (PDFs/imágenes).
- Machine Learning para predicción de comportamiento de pago.

---

## ⚠️ Limitaciones conocidas

- El formato del extracto bancario está fijo a 10 columnas sin encabezado. Si el banco cambia el contrato, el parser debe ajustarse.
- La cartera de SAP incluye filas de subtotal por cliente que deben filtrarse.
- Los nombres de cliente en el extracto aparecen truncados (~30 caracteres), por lo que el matching por nombre requiere coincidencia parcial.

---

## 📄 Confidencialidad

Este proyecto se desarrolla bajo Acuerdo de Confidencialidad (NDA) con +logística. Los archivos con información real de la empresa no se incluyen en este repositorio y no deben compartirse fuera del equipo del reto.

---

## 👥 Equipo

Reto 10 — Programa Beca SER ANDI Inteligencia Artificial
