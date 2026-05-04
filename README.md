# Automatización de Gestión de Cartera — +logística

> **Reto 10 · Programa Beca SER ANDI — Inteligencia Artificial**
> Operado por NODO / Universidad EAFIT · Abril 2026

MVP académico que automatiza el proceso semanal de gestión de cartera de +logística. A partir del extracto bancario y la cartera exportada de SAP, la herramienta identifica pagos, los cruza con las facturas pendientes, clasifica la cartera por antigüedad, registra decisiones humanas sobre los casos ambiguos y entrega un dashboard de priorización para el analista.

---

## 📌 Estado del proyecto

| Fase | Estado |
|---|---|
| Entendimiento (AS-IS) | ✅ Completado |
| Diseño TO-BE | ✅ Completado |
| Automatización (MVP) | ✅ Completado — end-to-end funcional con dashboard y ciclo de aprendizaje |
| Monitoreo y presentación | 🚧 En curso |

---

## 🧭 ¿Cómo funciona la herramienta? (resumen de alto nivel)

El flujo end-to-end se ejecuta en dos comandos:

1. **`python run_pipeline.py`** — orquesta los 6 pasos de procesamiento:
   1. **Parser del extracto** → lee el CSV plano del banco y lo estructura.
   2. **Clasificador de movimientos** → separa abonos de clientes, egresos, comisiones e intereses.
   3. **Parser de cartera SAP** → lee el Excel de cartera y calcula días de vencimiento y bandas de antigüedad.
   4. **Matching pago↔factura** → aplica una cascada de cuatro niveles de confianza: decisión previa registrada, match exacto por valor, match acumulado (suma de varias facturas) y match por referencia/alias.
   5. **Consolidación** → genera `base_consolidada.csv` (una fila por factura, con pagos aplicados y estado) y `excepciones.csv` (pagos que no pudieron resolverse con confianza).
   6. **Persistencia del historial** → guarda la huella de cada pago resuelto en `historial_pagos.csv`. En corridas posteriores, los pagos ya conciliados se omiten para evitar duplicidades.

2. **`streamlit run app/streamlit_app.py`** — abre el dashboard con cuatro vistas:
   - **📊 Estado de cartera:** KPIs, distribución por banda de antigüedad, tabla filtrable por cliente / prioridad / estado / banda, y descarga en CSV.
   - **⚠️ Excepciones por resolver:** formularios que permiten al analista decidir qué hacer con cada pago ambiguo o no identificado (aplicar a una factura específica, agregar alias, marcar como cliente nuevo, marcar como pago parcial, dejar pendiente, descartar). La decisión queda registrada y se aplicará automáticamente en la próxima corrida.
   - **📜 Decisiones registradas:** auditoría histórica de todas las decisiones tomadas por el analista, con opción de revertir cualquiera de ellas (al revertir, el pago vuelve a la cascada normal en la próxima corrida).
   - **📧 Generar correos de seguimiento:** copy listo para enviar por cliente, con plantilla adaptada a la etapa de gestión según la banda más vencida.

Adicionalmente, el dashboard expone un panel **⚙️ Procesar nueva corrida** en la barra lateral que permite al analista subir el extracto y la cartera del día y ejecutar el pipeline completo sin salir del navegador.

---

## 🧠 Ciclo de aprendizaje del sistema

El sistema mantiene un "cerebro" persistido en disco que evoluciona corrida tras corrida:

- **`data/output/decisiones_analista.csv`** — cada decisión que el analista toma en la vista de excepciones queda registrada con una huella estable del pago (descripción + monto + fecha). En la siguiente corrida, el matcher consulta este archivo y reaplica la decisión automáticamente.
- **`data/reference/alias_clientes.csv`** — catálogo de equivalencias entre nombres del banco y nombres del cliente en SAP. Crece con cada `AGREGAR_ALIAS` que el analista registra.
- **`data/output/historial_pagos.csv`** — huellas de pagos ya conciliados. Evita que un pago se reaplique dos veces sobre la cartera.

**Validación defensiva.** Antes de reaplicar una decisión histórica, el matcher verifica que las facturas referenciadas sigan vigentes en la cartera actual. Si la factura ya no existe (porque SAP la conció o anuló), la decisión se descarta y el pago vuelve a la cascada normal — el sistema nunca aplica memoria a ciegas.

Para ver este flujo completo en consola con datos sintéticos, ejecuta:

```bash
python demo_ciclo_aprendizaje.py --pausas
```

El demo ejecuta tres corridas (sin memoria → con memoria aprendida → con cartera modificada para forzar la validación defensiva) y es autocontenido — no toca `data/output/`.

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

Verás en consola el resumen de cada paso: movimientos parseados, clasificación aplicada, facturas leídas, matches encontrados, excepciones detectadas y pagos persistidos en el historial. Al finalizar se generan tres archivos en `data/output/`:

- `base_consolidada.csv` — una fila por factura con toda la información unificada.
- `excepciones.csv` — pagos que no pudieron resolverse automáticamente.
- `historial_pagos.csv` — huellas de los pagos resueltos, para evitar duplicidades en corridas posteriores.

### 5. Lanzar el dashboard

```bash
streamlit run app/streamlit_app.py
```

Se abrirá automáticamente el navegador en `http://localhost:8501`. Desde la barra lateral puedes:
- Alternar entre las cuatro vistas del dashboard.
- Ejecutar una nueva corrida del pipeline cargando archivos directamente desde el navegador (panel **⚙️ Procesar nueva corrida**).
- Refrescar la vista cuando los archivos de `data/output/` cambien por una corrida ejecutada en consola (botón **🔄 Refrescar vista**).

---

## 🧠 Reglas de negocio implementadas

| Regla | Implementación |
|---|---|
| Clasificación de movimientos bancarios | Reglas deterministas sobre código DOC y descripción normalizada |
| Cascada de matching | (1) decisión previa de la analista → (2) match exacto por valor → (3) match acumulado → (4) match por referencia |
| Match acumulado | Búsqueda combinatoria acotada: suma de N facturas del mismo cliente = monto del pago |
| Match por alias/referencia | Diccionario de alias (`data/reference/alias_clientes.csv`) para resolver nombres truncados del banco |
| Clasificación de cartera | Bandas de antigüedad: AL_DIA / 0-30 / 31-60 / 61-90 / 91-120 / 121+ |
| Priorización | `CRITICO` (>60 días) → `ALTO` → `MEDIO` → `BAJO` → `RESUELTO` |
| **Pago no asociable con confianza** | **Nunca se aplica arbitrariamente.** Queda en `excepciones.csv` con el estado `AMBIGUO`, `NO_IDENTIFICADO` o `CLIENTE_DESCONOCIDO` para gestión humana. |
| **Validación defensiva del aprendizaje** | Antes de reaplicar una decisión histórica, el matcher verifica que las facturas referenciadas sigan en la cartera actual. Si no, descarta la decisión y devuelve el pago a la cascada normal. |

---

## 📁 Estructura del repositorio

```
cartera_maslogistica/
├── app/
│   └── streamlit_app.py          # Dashboard (4 vistas + panel de carga)
├── data/
│   ├── input/                    # Archivos de entrada (NDA — no versionados)
│   ├── reference/
│   │   └── alias_clientes.csv    # Catálogo aprendido de alias banco↔SAP
│   └── output/
│       ├── base_consolidada.csv  # Una fila por factura
│       ├── excepciones.csv       # Pagos para revisión humana
│       ├── decisiones_analista.csv  # "Cerebro" — decisiones registradas
│       └── historial_pagos.csv   # Pagos ya conciliados (anti-duplicidad)
├── src/
│   ├── parser_extracto.py        # Paso 1 — lee el CSV del banco
│   ├── clasificador.py           # Paso 2 — clasifica movimientos
│   ├── parser_cartera.py         # Paso 3 — lee la cartera SAP
│   ├── matcher.py                # Paso 4 — cascada pago↔factura
│   ├── consolidador.py           # Paso 5 — genera base consolidada
│   ├── registro_decisiones.py    # Persistencia de decisiones e historial
│   ├── plantillas_correos.py     # Copys oficiales por etapa de gestión
│   └── generar_datos_demo.py     # Generador de datos sintéticos
├── notebooks/                    # Exploración y pruebas paso a paso
├── tests/                        # Pruebas unitarias
├── run_pipeline.py               # Orquestador end-to-end
├── demo_ciclo_aprendizaje.py     # Demo en consola del ciclo aprendizaje
├── requirements.txt
├── .gitignore
└── README.md
```

---

## 🎯 Alcance del MVP

**Dentro del alcance:**

- Carga manual de archivos (extracto + cartera), por consola o por dashboard.
- Clasificación automática de movimientos bancarios por reglas deterministas.
- Matching de pagos con facturas por valor exacto, acumulado, alias y referencia.
- Base consolidada con trazabilidad del método de match.
- Dashboard de priorización con filtros y descarga.
- Registro de decisiones del analista sobre excepciones, con auditoría y reversión.
- Aplicación automática de decisiones previas en corridas siguientes (ciclo de aprendizaje).
- Validación defensiva: descarte de decisiones obsoletas cuando la realidad cambió.
- Generación asistida de correos de seguimiento por cliente y etapa de gestión.

**Fuera del alcance:**

- Integración directa con SAP o portal bancario.
- Envío automático de correos (la herramienta solo prepara el copy).
- Procesamiento de soportes de pago (PDFs / imágenes).
- Machine Learning para predicción de comportamiento de pago.
- Actualización automática de saldos por pagos parciales (ver Limitaciones).

---

## 🚧 Pendientes y mejoras futuras

- **Cierre del ciclo de pago parcial.** Hoy una decisión `PAGO_PARCIAL` queda registrada y reaparece en cada corrida hasta que el analista ajuste la factura en SAP. Falta lógica que reduzca el saldo de la factura en `base_consolidada.csv` consumiendo las decisiones previas.
- **Validación con datos reales de +logística.** La lógica está probada con el set sintético; resta correrla contra un extracto y una cartera reales del período vigente.
- **Afinamiento del match por alias.** Hoy usa coincidencia por substring; un `fuzzy matching` (rapidfuzz) reduciría falsos negativos cuando el banco trunca nombres de forma inconsistente.
- **Persistencia histórica.** Cada corrida sobrescribe la base consolidada. Para análisis de tendencias habría que versionar o apendear los resultados.
- **Pruebas unitarias.** El directorio `tests/` existe pero aún no tiene cobertura; conviene empezar por el matcher y el clasificador, donde está la lógica crítica.

---

## ⚠️ Limitaciones conocidas

- El formato del extracto bancario está fijo a 10 columnas sin encabezado. Si Bancolombia cambia el contrato, el parser debe ajustarse.
- La cartera de SAP incluye filas de subtotal por cliente que deben filtrarse.
- Los nombres de cliente en el extracto aparecen truncados (~30 caracteres), por lo que el matching por nombre requiere coincidencia parcial o alias registrado.
- **Pagos parciales:** la herramienta registra la decisión pero no actualiza el saldo de la factura. El ajuste contable se sigue haciendo manualmente en SAP, y la excepción reaparece en cada corrida hasta que SAP refleje el cambio.

---

## 📄 Confidencialidad

Este proyecto se desarrolla bajo Acuerdo de Confidencialidad (NDA) con +logística. Los archivos con información real de la empresa **no se incluyen en este repositorio** y no deben compartirse fuera del equipo del reto. Todo lo que se ve en la demo corre sobre datos sintéticos generados localmente.

---

## 👥 Equipo

Reto 10 — Programa Beca SER ANDI Inteligencia Artificial · Abril 2026
