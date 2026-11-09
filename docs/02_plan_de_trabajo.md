# Plan de trabajo

> Ajustar las semanas a la fecha de entrega real.

## Roles

| Rol | Responsable | Tareas | Carpeta/archivos |
|---|---|---|---|
| Datos y flujo | _(asignar)_ | Calidad de datos, mapeo de conceptos OMOP, reconstrucción del flujo, process mining | `notebooks/01`, `02`, `src/quality.py`, `src/flow.py` |
| Congestión y pronóstico | _(asignar)_ | Ocupación horaria, pronóstico de demanda, alerta de saturación | `notebooks/03`, `05` |
| Modelado explicable | _(asignar)_ | Features, modelo LOS, SHAP, perfiles de pacientes | `notebooks/04`, `src/features.py`, `src/models.py` |
| Power BI y documentación | _(asignar)_ | Modelo de datos en Power BI, dashboard, documento final, README | `powerbi/`, `docs/` |

La simulación (`notebooks/06`) la hace quien termine primero, con apoyo de todos.

## Cronograma

| Semana | Objetivo | Entregable interno |
|---|---|---|
| 1 | Cargar datos, calidad, mapear conceptos, EDA base | `01_calidad_datos.ipynb` corrido + lista de problemas de datos |
| 2 | Flujo (event log, transiciones, variantes) + ocupación | Mapa del proceso y top cuellos de botella |
| 3 | Modelo LOS + SHAP · pronóstico de saturación | Métricas + gráficos SHAP + pronóstico validado |
| 4 | Simulación what-if · exportar tablas a Power BI | Escenarios cuantificados + `data/processed/*.csv` |
| 5 | Dashboard, documento, README, ensayo de presentación | Entrega final |

## Reglas del repo

- Nunca subir datos crudos (`data/raw/` está en `.gitignore`).
- Notebooks numerados y que corran de principio a fin.
- Funciones reutilizables en `src/`, no copiadas entre notebooks.
- Cada hallazgo importante se anota en `docs/hallazgos.md` con gráfico y frase de una línea.
