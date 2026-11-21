# Data Challenge HUN 2026 — Flujo de pacientes del Hospital Universidad del Norte

> **Reto:** comprender, predecir y optimizar el flujo de pacientes, identificando cuellos de botella, patrones operacionales y oportunidades de mejora en los tiempos de atención.

## Enfoque

```
DIAGNÓSTICO           →  EXPLICACIÓN          →  PREDICCIÓN            →  ACCIÓN
Process mining +         Modelo LOS + SHAP       Pronóstico de            Simulación what-if
ocupación horaria        (factores de demora)    saturación + alerta      (impacto cuantificado)
```

Detalle completo en [`docs/01_posibles_soluciones.md`](docs/01_posibles_soluciones.md).

## Dashboard interactivo (web)

**[Abrir el dashboard →](https://lesteban1828.github.io/Data-challenge-HUN/)** · código en [`dashboard/`](dashboard/) · solo datos agregados, sin información de pacientes.

| Página | Qué se puede hacer |
|---|---|
| Resumen | Filtrar por periodo (año, últimos 12 meses o rango libre): los KPI se recalculan y muestran la variación. Clic en un mes o en un tipo de episodio para ver su detalle. |
| Flujo | Diagrama Sankey del recorrido (llegada → triage → atención → hospitalización) con reprocesos y retornos. Deslizador de **meta de espera de cama**: muestra qué % de pacientes la cumple. |
| Congestión | Mapas de calor día × hora con detalle al pasar el cursor; clic en un día para ver el desfase entre llegadas y ocupación. Umbral de saturación ajustable. |
| Factores | SHAP de los 3 modelos y número de variables ajustable; tabla de diagnósticos con búsqueda, orden y comparación contra el promedio. |
| Pronóstico | Real vs Holt-Winters/LightGBM. Umbral de alerta ajustable con **matriz de confusión en vivo** (aciertos, falsas alarmas y días no detectados). |
| Simulador | **Simulación de la cola de camas en el navegador**, calibrada con el notebook 06: camas, estancia, hora del alta y demanda. Escenarios predefinidos y recomendaciones que se cargan con un clic. |

Atajos: <kbd>←</kbd> <kbd>→</kbd> cambian de página, <kbd>P</kbd> activa el modo presentación y cada gráfico se descarga como PNG.
Cada página tiene su propio enlace para compartir (`#flujo`, `#escenarios`…).

## Estructura

```
Data_Challenge_HUN_2026/
├── data/
│   ├── raw/          ← datos originales del reto (NO se suben a GitHub)
│   ├── sample/       ← datos sintéticos para pruebas (scripts/generar_datos_sinteticos.py)
│   ├── interim/      ← tablas intermedias (event log, features)
│   └── processed/    ← resultados y tablas para Power BI
├── docs/             ← bases, soluciones, plan, diccionario, hallazgos
├── notebooks/        ← análisis numerado 01 → 07
├── src/              ← funciones reutilizables
├── scripts/          ← utilidades
├── sql/              ← consultas para DBeaver
├── .env.example      ← plantilla de credenciales (copiar como .env, no se sube)
├── powerbi/          ← archivo .pbix y guía del dashboard
├── reports/figures/  ← gráficos para el documento
└── models/           ← modelos entrenados
```

| Notebook | Contenido |
|---|---|
| 01_calidad_datos | Volumen, fechas, nulos, huérfanos, conceptos a mapear |
| 02_flujo_process_mining | Event log, duración de etapas, esperas entre etapas, variantes, mapa pm4py |
| 03_congestion_ocupacion | Ocupación horaria, heatmaps, efecto de la congestión en la estancia |
| 04_modelo_estancia_shap | LightGBM (al ingreso / explicativo), estancia prolongada, SHAP |
| 05_pronostico_saturacion | Holt-Winters y LightGBM, alerta de saturación |
| 06_simulacion_what_if | SimPy calibrado con datos reales, escenarios de mejora |
| 07_export_powerbi | Modelo estrella en CSV para el dashboard |

## Cómo correr

```powershell
conda create -n hun python=3.11 -y
conda activate hun
pip install -r requirements.txt

# Probar con datos sintéticos (mientras llegan los reales)
python scripts/generar_datos_sinteticos.py --visitas 5000
# luego en los notebooks: SOURCE = "sample"
jupyter lab
```

### Con la base de datos del reto (FortiClient VPN + DBeaver) — flujo real

La base `uhn_i` (esquema `uninorte_omop`) es **de solo lectura** y pesa ~25 GB, así que **el trabajo pesado se
hace en el servidor** y al computador solo bajan tablas resumidas (~150 MB), que se guardan en
**`D:/HUN_DataChallenge_datos/`** (el disco C: está lleno; se cambia con `HUN_DATA_DIR` en `.env`).

1. Conectar **FortiClient VPN**.
2. Copiar `.env.example` como `.env` y llenarlo con los datos de DBeaver (la contraseña la escribe cada uno).
3. Probar: `python -c "from src import db; db.test_connection(); print(db.row_counts())"`
4. Extraer las tablas resumidas (≈15 min, una sola vez): `python -m src.extract`
5. Correr los notebooks 01 → 07 (`jupyter nbconvert --to notebook --execute --inplace notebooks/0*.ipynb`).
   Se regeneran con `python scripts/build_notebooks.py`.

| Archivo en `D:/HUN_DataChallenge_datos/interim/` | Contenido |
|---|---|
| `etapas.parquet` | 1,57 M etapas únicas de urgencias/hospitalización con su episodio |
| `episodios.parquet` | 694 509 episodios con variables clínicas resumidas en el servidor |
| `proc_por_visita.parquet`, `conceptos.parquet`, `top_dx`, `top_labs` | apoyos |
| `mensual_tablas.parquet`, `calidad_intervalos.parquet` | calidad de datos |

**Episodio de urgencias** = cadena de etapas (triage 9203 → atención urgencias 3045729 → hospitalización 9201)
de la misma persona con < 6 h entre una y otra. Se reconstruye porque `visit_occurrence` no trae duración y
mezcla etapas separadas por semanas (ver `docs/hallazgos.md`).

Consultas de resumen para correr directo en DBeaver: [`sql/consultas_resumen_dbeaver.sql`](sql/consultas_resumen_dbeaver.sql).
Guía de conexión: [`docs/04_conexion_vpn_dbeaver.md`](docs/04_conexion_vpn_dbeaver.md).

## Entregables

- [x] Documentación del proyecto (`docs/hallazgos.md` y documento final)
- [x] Repositorio GitHub
- [x] Dashboard Power BI (`powerbi/HUN_Flujo.pbip`)
- [x] Dashboard web interactivo con simulador what-if (`dashboard/`, publicado con GitHub Pages)

## Equipo

- Luis Esteban Mariño
- Ángel Mozo
- Abran Basto
