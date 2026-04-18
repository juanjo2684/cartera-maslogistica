# Automatización de Gestión de Cartera — +logística

> **Reto 10 · Programa Beca SER ANDI — Inteligencia Artificial**
> Operado por NODO / Universidad EAFIT · Abril 2026

MVP académico que automatiza el proceso semanal de gestión de cartera de +logística. A partir del extracto bancario y la cartera exportada de SAP, la herramienta identifica pagos, los cruza con las facturas pendientes, clasifica la cartera por antigüedad y entrega un dashboard de priorización para el analista.

---

## 📌 Estado del proyecto

| Fase | Estado |
|---|---|
| Entendimiento (AS-IS) | ✅ Completado |
| Diseño TO-BE | ✅ Completado |
| Automatización (MVP) | ✅ Completado — end-to-end funcional con dashboard |
| Monitoreo y presentación | 🚧 En curso |

---

## 🧭 ¿Cómo funciona la herramienta? (resumen de alto nivel)

El flujo end-to-end se ejecuta en dos comandos:

1. **`python run_pipeline.py`** — orquesta los 5 pasos de procesamiento:
   1. **Parser del extracto** → lee el CSV plano del banco y lo estructura.
   2. **Clasificador de movimientos** → separa abonos de clientes, egresos, comisiones e intereses.
   3. **Parser de cartera SAP** → lee el Excel de cartera y calcula días de vencimiento y bandas de antigüedad.
   4. **Matching pago↔factura** → aplica tres reglas en cascada: match exacto por valor, match acumulado (suma de varias facturas) y match por alias/referencia.
   5. **Consolidación** → genera `base_consolidada.csv` (una fila por factura, con pagos aplicados y estado) y `excepciones.csv` (pagos que no pudieron resolverse con confianza).

2. **`streamlit run app/streamlit_app.py`** — abre el dashboard con dos vistas:
   - **Estado de cartera:** KPIs, distribución por banda de antigüedad, tabla filtrable por cliente / prioridad / estado / banda, y descarga en CSV.
   - **Excepciones por resolver:** formularios que permiten al analista decidir qué hacer con cada pago ambiguo o no identificado (agregar alias, marcar como cliente nuevo, descartar). La decisión queda registrada y se aplicará en la próxima corrida.

---

## ⚠️ Datos sintéticos para la demostración

Los datos reales de +logística están bajo NDA, por lo que **el repositorio está configurado por defecto para correr con datos sintéticos** generados por `src/generar_datos_demo.py`. Estos datos replican la estructura exacta de los archivos reales y cubren a propósito los escenarios que la solución debe manejar:

| Escenario | Caso incluido en la demo |
|---|---|
| Match exacto | ALMACENES GLOBALES paga $7,051,557 = FV-1010 |
| Match acumulado (2 facturas) | TRANSPORTES DEL NORTE paga $3,500,000 = FV-1002 + FV-1003 |
| Match acumulado (2 facturas) | COMERCIALIZADORA PACIFIC paga $8,000,000 = FV-1020 + FV-1021 |
| **Excepción — Ambiguo** | LOGISTICA INTEGRADA paga $1,500,000 → coincide con FV-1040 *y* FV-1041 |
| **Excepción — No identificado** | TEXTILES MODERNOS paga $4,200,000 pero no está en la cartera |
| **Excepción — Pago parcial** | QUIMICOS ANDINOS paga $1,500,000 y debe $2,800,000 |
| Cartera crítica sin pago | INDUSTRIAS METÁLICAS DEL SUR: $21.4M vencidos 61-130 días |
| Cartera al día | EMPAQUES Y SOLUCIONES: $10.3M por vencer |
| Cartera vencida 91-120 | DISTRIBUIDORA CENTRAL: $9.5M vencidos 95 días |
| Ruido filtrado | 5 egresos, 1 abono de intereses, 2 gastos bancarios |

De esta forma puede ver el comportamiento completo de la solución sin exponer información confidencial.

---

## 🚀 Instalación y ejecución paso a paso

### Requisitos previos

- Python 3.10 o superior
- Git

### 1. Clonar el repositorio

```bash
git clone https://github.com/<tu-usuario>/cartera-maslogistica.git
cd cartera-maslogistica
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

### 3. Generar los datos sintéticos de demostración

```bash
python src/generar_datos_demo.py
```

Esto crea `EXTRACTO_BANCARIO_demo.csv` y `cartera_demo.xlsx` dentro de `data/input/`. Estos son los archivos que consume el pipeline por defecto.

### 4. Ejecutar el pipeline completo

```bash
python run_pipeline.py
```

Verás en consola el resumen de cada paso: movimientos parseados, clasificación aplicada, facturas leídas, matches encontrados y excepciones detectadas. Al finalizar se generan dos archivos en `data/output/`:

- `base_consolidada.csv` — una fila por factura con toda la información unificada.
- `excepciones.csv` — pagos que no pudieron resolverse automáticamente.

### 5. Lanzar el dashboard

```bash
streamlit run app/streamlit_app.py
```

Se abrirá automáticamente el navegador en `http://localhost:8501`. Desde la barra lateral puedes alternar entre la vista de **Estado de cartera** y **Excepciones por resolver**.

> **Nota:** Si se modifican los archivos de `data/output/`, basta con pulsar el botón de recargar en Streamlit o reiniciar la app para ver los cambios.

---

## 🧠 Reglas de negocio implementadas

| Regla | Implementación |
|---|---|
| Clasificación de movimientos bancarios | Reglas deterministas sobre código DOC y descripción normalizada |
| Match exacto por valor | Comparación numérica directa entre monto del pago y saldo de una factura |
| Match acumulado | Búsqueda combinatoria acotada: suma de N facturas del mismo cliente = monto del pago |
| Match por alias/referencia | Diccionario de alias (`data/reference/alias_clientes.csv`) para resolver nombres truncados del banco |
| Clasificación de cartera | Bandas de antigüedad: AL_DIA / 0-30 / 31-60 / 61-90 / 91-120 / 121+ |
| Priorización | `CRITICO` (>60 días) → `ALTO` → `MEDIO` → `BAJO` → `RESUELTO` |
| **Pago no asociable con confianza** | **Nunca se aplica arbitrariamente.** Queda en `excepciones.csv` con el estado `AMBIGUO`, `NO_IDENTIFICADO` o `CLIENTE_DESCONOCIDO` para gestión humana |

---

## 📁 Estructura del repositorio

```
cartera_maslogistica/
├── app/
│   └── streamlit_app.py          # Dashboard (vistas de cartera y excepciones)
├── data/
│   ├── input/                    # Archivos de entrada (NDA — no versionados)
│   ├── reference/                # Alias de clientes, catálogos
│   └── output/                   # base_consolidada.csv, excepciones.csv
├── src/
│   ├── parser_extracto.py        # Paso 1 — lee el CSV del banco
│   ├── clasificador.py           # Paso 2 — clasifica movimientos
│   ├── parser_cartera.py         # Paso 3 — lee la cartera SAP
│   ├── matcher.py                # Paso 4 — cruza pagos con facturas
│   ├── consolidador.py           # Paso 5 — genera base consolidada
│   ├── registro_decisiones.py    # Persistencia de decisiones del analista
│   └── generar_datos_demo.py     # Generador de datos sintéticos
├── notebooks/                    # Exploración y pruebas paso a paso
├── tests/                        # Pruebas unitarias
├── run_pipeline.py               # Orquestador end-to-end
├── requirements.txt
├── .gitignore
└── README.md
```

---

## 🎯 Alcance del MVP

**Dentro del alcance:**

- Carga manual de archivos (extracto + cartera).
- Clasificación automática de movimientos bancarios por reglas deterministas.
- Matching de pagos con facturas por valor exacto, acumulado y alias.
- Base consolidada con trazabilidad del método de match.
- Dashboard de priorización con filtros y descarga.
- Registro de decisiones del analista sobre excepciones.

**Fuera del alcance:**

- Integración directa con SAP o portal bancario.
- Envío automático de correos de seguimiento.
- Procesamiento de soportes de pago (PDFs / imágenes).
- Machine Learning para predicción de comportamiento de pago.

---

## 🚧 Pendientes y mejoras futuras

- **Aplicación automática de decisiones del analista en la próxima corrida.** Actualmente las decisiones que el analista toma en la vista de excepciones se registran en disco (`registro_decisiones.py` guarda la huella del pago, la acción elegida y los datos asociados), y los alias nuevos sí quedan disponibles para la siguiente corrida del pipeline. Sin embargo, **falta cerrar el ciclo**: que el matcher consulte el registro de decisiones y aplique automáticamente las decisiones previas (ej. "este pago ambiguo ya fue resuelto como FV-1040") sin que el analista tenga que repetirlas.
- **Validación con datos reales de +logística.** La lógica está probada con el set sintético; resta correrla contra un extracto y una cartera reales del período vigente.
- **Afinamiento del match por alias.** Hoy usa coincidencia por prefijo de descripción; un `fuzzy matching` (rapidfuzz) reduciría falsos negativos cuando el banco trunca nombres de forma inconsistente.
- **Persistencia histórica.** Cada corrida sobreescribe la base consolidada. Para análisis de tendencias habría que versionar o apendear los resultados.
- **Pruebas unitarias.** El directorio `tests/` existe pero aún no tiene cobertura; conviene empezar por el matcher y el clasificador que es donde está la lógica crítica.

---

## ⚠️ Limitaciones conocidas

- El formato del extracto bancario está fijo a 10 columnas sin encabezado. Si Bancolombia cambia el contrato, el parser debe ajustarse.
- La cartera de SAP incluye filas de subtotal por cliente que deben filtrarse.
- Los nombres de cliente en el extracto aparecen truncados (~30 caracteres), por lo que el matching por nombre requiere coincidencia parcial o alias registrado.

---

## 📄 Confidencialidad

Este proyecto se desarrolla bajo Acuerdo de Confidencialidad (NDA) con +logística. Los archivos con información real de la empresa **no se incluyen en este repositorio** y no deben compartirse fuera del equipo del reto. Todo lo que se ve en la demo corre sobre datos sintéticos generados localmente.

---

## 👥 Equipo

Reto 10 — Programa Beca SER ANDI Inteligencia Artificial · Abril 2026
