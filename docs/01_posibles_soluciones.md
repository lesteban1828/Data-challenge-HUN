# Posibles soluciones — Data Challenge HUN 2026

> **Pregunta del reto:** comprender, predecir y optimizar el flujo de pacientes del Hospital Universidad del Norte, identificando cuellos de botella, patrones operacionales y oportunidades de mejora en los tiempos de atención.
>
> **Entregables:** documentación · repositorio GitHub · dashboard en Power BI.
> **Lo que más pesa:** hallazgos estratégicos, interpretabilidad, visualización efectiva y recomendaciones accionables.

---

## 0. Idea central para ganar

La mayoría de equipos va a entregar "EDA + un modelo de regresión + un dashboard". Para destacar, la propuesta debe contar **una historia completa de punta a punta**:

```
DIAGNÓSTICO            →  EXPLICACIÓN            →  PREDICCIÓN             →  ACCIÓN
¿Cómo fluye el          ¿Por qué se             ¿Cuándo va a            ¿Qué cambiar y
paciente y dónde se     demora? (factores,      saturarse? ¿Cuánto      cuánto se gana?
atasca? (process        SHAP)                   durará esta visita?     (simulación what-if)
mining, ocupación)                              (forecast + LOS)
```

Cada sección del dashboard y del documento corresponde a una de estas cuatro etapas. El cierre con **simulación cuantificada** ("si se agrega X en la franja Y, la espera baja Z%") es el elemento diferenciador.

---

## 1. Solución A — Reconstrucción del flujo con Process Mining ⭐ (prioridad máxima)

**Qué es.** Tratar `VISIT_DETAIL` como un *event log*: cada `visit_occurrence_id` es un caso, cada `visit_detail_concept_id` es una actividad, y los `*_start/_end_datetime` son las marcas de tiempo.

**Por qué encaja.** En OMOP, `VISIT_DETAIL` fue pensada precisamente para registrar los movimientos del paciente entre unidades dentro de una misma visita (p. ej. UCI → hospitalización), que luego se agregan en un único registro de `VISIT_OCCURRENCE` ([OHDSI, Blacketer](https://www.ohdsi.org/wp-content/uploads/2021/09/4-Blacketer_Visit_Detail_abstract.pdf)). Además ya existe un método publicado para extraer event logs desde OMOP CDM y analizar procesos de hospitalización, consulta externa y urgencias con process mining ([PLoS ONE 2023](https://doaj.org/article/9ad345bb1d2a4a93a11fb5c6b9e0679f)) — citarlo da respaldo metodológico.

**Cómo.**
1. Ordenar etapas por visita → secuencia (traza) de cada paciente.
2. Calcular por etapa: duración (`end − start`) y **espera previa** (`start_etapa − end_etapa_anterior`). La espera entre etapas es el cuello de botella "invisible".
3. Con `pm4py`: mapa de procesos (DFG con frecuencia y tiempo), **variantes** más comunes, conformance checking.
4. Matriz de transiciones (etapa → siguiente) con mediana y P90 de espera.

**Resultado para el dashboard.** Diagrama de flujo/Sankey con grosor = volumen y color = espera. Ranking de transiciones más lentas.

**Riesgos.** Logs hospitalarios suelen ser "espagueti" (muchas variantes raras). La literatura reciente de process mining en urgencias reporta fragmentación de variantes y necesidad de limpiar registros en ráfaga antes de descubrir el proceso ([arXiv, ED process mining](https://arxiv.org/pdf/2609.32010)). Solución: agrupar etapas de baja frecuencia y filtrar el top-N de variantes que cubra ~80% de los casos.

---

## 2. Solución B — Congestión y ocupación (censo horario)

**Qué es.** Calcular cuántos pacientes hay dentro del hospital (o de cada servicio/etapa) en cada hora.

**Cómo.** Cada visita aporta +1 en su inicio y −1 en su fin; suma acumulada → ocupación. Repetir por `visit_concept_id` y por etapa de `VISIT_DETAIL`.

**Hallazgos esperables.**
- Heatmap hora × día de la semana de **llegadas** vs. **ocupación** (el pico de ocupación suele ir varias horas detrás del pico de llegadas).
- Franjas donde llegadas > salidas sostenidamente = acumulación.
- Relación ocupación al llegar ↔ duración de la estancia (efecto congestión).

**Por qué importa.** Es la base de la alerta temprana (Solución D) y una variable clave del modelo (Solución C).

---

## 3. Solución C — Modelo explicable de tiempos de atención / estancia ⭐

**Qué es.** Predecir la duración de la visita (LOS) o la espera en una etapa, y explicar qué la aumenta.

**Evidencia.** Los estudios de predicción de LOS coinciden en usar *gradient boosting* con SHAP para interpretabilidad: XGBoost tuvo el menor error frente a otros ocho modelos en un servicio de medicina general ([Zeleke et al., 2024](https://doaj.org/article/b6a70c13ed314be3a96c1432a07f0075)), y en urgencias se ha usado Histogram Gradient Boosting explicado con SHAP y LIME ([PredictED, 2025](https://www.atlantis-press.com/proceedings/wctp-24/126010287)). Un hallazgo muy útil para nosotros: incorporar **variables de cola** que capturan el estado del servicio en tiempo real mejora la predicción de estancia prolongada ([AHFE, Italia](https://openaccess.cms-conferences.org/publications/book/978-1-964867-36-6/article/978-1-964867-36-6_18)).

**Variables candidatas (todas derivables de las tablas del reto).**

| Grupo | Variables |
|---|---|
| Paciente | edad (`year_of_birth`), sexo (`gender_concept_id`) |
| Visita | tipo (`visit_concept_id`), origen (`visit_type_concept_id`), hora/día/mes de llegada, fin de semana/festivo |
| Congestión (cola) | ocupación total y del servicio al llegar, llegadas en la última hora/6 h |
| Complejidad | nº diagnósticos, nº procedimientos, nº mediciones, nº etapas, diagnóstico principal (agrupado) |
| Historia | visitas previas en 30/90 días, `preceding_visit_occurrence_id` no nulo (reingreso) |
| Profesional | carga del `provider_id` ese día (opcional) |

**Dos versiones del modelo (clave para no hacer trampa):**
- **Al ingreso:** solo variables conocidas al momento de llegar → útil para planeación. *No usar* conteos de procedimientos/mediciones totales (fuga de información).
- **Explicativo:** todas las variables → útil para entender factores.

**Formulación.** Regresión de `log(LOS)` + clasificación de **estancia prolongada** (> P75 o > umbral clínico). Validación con **corte temporal** (entrenar en meses antiguos, probar en recientes), no split aleatorio. Alternativa avanzada: análisis de supervivencia (Cox / gradient boosting survival) con SHAP, que maneja visitas aún abiertas como censuradas ([IOS Press, 2024](https://ebooks.iospress.nl/pdf/doi/10.3233/SHTI240505)).

**Resultado para el dashboard.** Importancia global (SHAP), dependencias (p. ej. LOS vs. hora de llegada), y explicación individual de casos atípicos.

---

## 4. Solución D — Pronóstico de demanda y alerta temprana de saturación

**Qué es.** Pronosticar llegadas y ocupación por hora/día y avisar cuando se espera superar un umbral.

**Evidencia.** Un sistema prospectivo en un hospital universitario finlandés pronosticó la saturación de la siguiente hora con AUC nominal de 0.98 y la de 24 h con 0.79 usando solo métodos estadísticos estacionales tipo Holt-Winters ([Tuominen et al., arXiv](https://arxiv.org/pdf/2301.09108)). Los autores defienden que el objetivo debe ser la saturación **categórica** (sí/no) y no solo el número de llegadas, y que un sistema de alerta necesita una definición clara de crisis y un margen de tiempo para actuar ([Springer 2024](https://link.springer.com/article/10.1007/s10916-024-02137-0)).

**Cómo.**
1. Serie horaria de llegadas y ocupación (de la Solución B).
2. Baselines: naive estacional, Holt-Winters / ETS, SARIMA; luego Prophet o LightGBM con rezagos y calendario (festivos colombianos con `holidays`).
3. Definir "saturación" = ocupación > P90 histórico (o umbral que indique el hospital).
4. Evaluar como clasificación (AUC, sensibilidad) a 1 h, 6 h y 24 h.

**Resultado para el dashboard.** Semáforo de riesgo de saturación por franja + curva de pronóstico con intervalo.

---

## 5. Solución E — Detección de patrones atípicos

- Estancias atípicas por tipo de visita (z-score robusto / percentiles condicionales / Isolation Forest).
- Trayectorias raras (variantes de baja frecuencia con tiempos altos).
- Reingresos tempranos usando `preceding_visit_occurrence_id` y visitas del mismo `person_id` en ≤ 30 días.
- Segmentación de perfiles de paciente (k-prototypes / clustering sobre edad, complejidad, tipo de visita) → "¿cómo se comportan distintos perfiles?" que pide el reto literalmente.

---

## 6. Solución F — Simulación what-if (el remate) ⭐

**Qué es.** Simulación de eventos discretos con `SimPy`: llegadas según el patrón horario real, etapas con tiempos de servicio muestreados de los datos, capacidad por etapa.

**Cómo.**
1. Calibrar: que la simulación reproduzca las esperas observadas (validación).
2. Escenarios: +1 recurso en la etapa cuello de botella en la franja pico; redistribuir turnos; reducir la espera de una transición específica en X%.
3. Reportar el impacto en espera promedio, P90 y estancia total.

**Por qué gana.** Convierte hallazgos en recomendaciones con número, que es exactamente lo que el hospital puede usar para decidir.

**Riesgo.** Sin datos de capacidad real (camas, personal), la capacidad se infiere de la ocupación máxima observada. Declararlo como supuesto.

---

## 7. Priorización

| Solución | Impacto en jurados | Esfuerzo | Prioridad |
|---|---|---|---|
| A. Process mining del flujo | Muy alto | Medio | **1** |
| B. Ocupación / congestión | Alto | Bajo | **1** |
| C. Modelo LOS + SHAP | Muy alto | Medio | **2** |
| D. Alerta de saturación | Alto | Medio | **3** |
| F. Simulación what-if | Muy alto (diferenciador) | Medio-alto | **3** |
| E. Atípicos y perfiles | Medio | Bajo | 4 (si hay tiempo) |

**Combinación recomendada:** A + B + C como núcleo obligatorio; D y F como diferenciadores; E como complemento.

---

## 8. Riesgos de datos a revisar el día 1

1. **Vocabulario OMOP.** Los `*_concept_id` son números. Pedir la tabla `CONCEPT` o mapear con [Athena](https://athena.ohdsi.org). Referencias comunes: `visit_concept_id` 9201 = hospitalización, 9202 = ambulatoria, 9203 = urgencias, 262 = urgencias + hospitalización; `gender_concept_id` 8507 = masculino, 8532 = femenino. **Verificar** con los datos reales.
2. **Calidad de fechas:** fin < inicio, horas exactamente 00:00 (solo fecha), visitas sin fin (aún abiertas), duraciones extremas.
3. **Integridad:** `VISIT_DETAIL` huérfanos, visitas sin etapas, etapas superpuestas en la misma visita.
4. **Fuga de información** en el modelo de ingreso (ver Solución C).
5. **Privacidad:** datos anonimizados; no subir datos crudos al GitHub público (ya está en `.gitignore`).

---

## 9. Estructura sugerida del dashboard Power BI

1. **Resumen ejecutivo:** KPIs (visitas, LOS mediana, % estancia prolongada, ocupación pico), tendencia.
2. **Flujo y cuellos de botella:** mapa de proceso/Sankey, ranking de esperas por transición, heatmap hora × día.
3. **Factores de demora:** SHAP global, segmentos de pacientes, comparativas por tipo de visita.
4. **Predicción y alerta:** pronóstico de ocupación, semáforo de saturación, predictor de LOS.
5. **Recomendaciones:** escenarios de simulación con impacto cuantificado.

---

## Fuentes

- [OHDSI — The VISIT_DETAIL: A Vehicle for Standard Visits (Blacketer)](https://www.ohdsi.org/wp-content/uploads/2021/09/4-Blacketer_Visit_Detail_abstract.pdf)
- [Exploring the potential of OMOP CDM for process mining in healthcare — PLoS ONE 2023](https://doaj.org/article/9ad345bb1d2a4a93a11fb5c6b9e0679f)
- [Process Mining of Patient Flow in an Emergency Department — arXiv](https://arxiv.org/pdf/2609.32010)
- [Process mining applications in healthcare: systematic review — PeerJ CS 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC11784703)
- [Comparison of nine ML regression models for hospital LOS — Zeleke et al. 2024](https://doaj.org/article/b6a70c13ed314be3a96c1432a07f0075)
- [PredictED: Explainable ESI classification and LOS prediction](https://www.atlantis-press.com/proceedings/wctp-24/126010287)
- [ML-based prediction of ED prolonged LOS: case study from Italy](https://openaccess.cms-conferences.org/publications/book/978-1-964867-36-6/article/978-1-964867-36-6_18)
- [Explainable time-to-event ML approach for ED LOS — IOS Press](https://ebooks.iospress.nl/pdf/doi/10.3233/SHTI240505)
- [Early Warning Software for ED Crowding — Tuominen et al.](https://arxiv.org/pdf/2301.09108)
- [Forecasting mortality-associated ED crowding — J Med Syst 2024](https://link.springer.com/article/10.1007/s10916-024-02137-0)
