# Hallazgos

> Datos reales: base `uhn_i`, esquema `uninorte_omop`, enero 2023 → abril 2026.
> **694 509 episodios de urgencias** de **253 683 pacientes** reconstruidos desde `visit_detail`.
> Cifras generadas por los notebooks 01–06. Los gráficos están en `reports/figures/`.

## Resumen en una frase

**El cuello de botella del HUN no está en la entrada de urgencias sino en la salida: el paciente que necesita
hospitalización espera una mediana de 16,7 h (P90 64 h) en urgencias por una cama. La hospitalización opera
casi al 100 % de su capacidad efectiva, así que pequeñas mejoras en la estancia hospitalaria
o en la hora de alta tienen un efecto grande en esa espera.**

## Tabla de hallazgos

| # | Hallazgo | Evidencia (número) | Gráfico | Recomendación | Notebook |
|---|---|---|---|---|---|
| 1 | **La espera de cama es el principal cuello de botella** | Urgencias → hospitalización: mediana **16,7 h**, P90 **64,3 h**, media 28,9 h desde la llegada hasta la cama (49 724 episodios) | `02_espera_hospitalizacion.png` | Indicador diario de "pacientes en espera de cama" y meta de < 6 h | 02 |
| 2 | **La congestión alarga la espera de cama** | Decil de menor ocupación: 14,4 h · 9.º decil: **21,2 h (+48 %)**. En observación el efecto es menor: 7,6 → 8,6 h (+13 %) | `03_congestion_vs_estancia.png` | Activar el protocolo de alta temprana / sala de egreso cuando la ocupación supere ~260 | 03 |
| 3 | **Más de la mitad de los episodios de urgencias dura < 15 min** | 373 054 episodios (55 %) son registro/triage o atención breve; los que pasan a observación (248 434) tienen mediana 8,1 h y P90 27,6 h | `01_distribucion_estancia.png` | Separar los indicadores (mezclar los dos grupos esconde la demora real); evaluar un *fast-track* | 01, 02 |
| 4 | **Patrón semanal y horario predecible** | Llegadas pico lunes y martes a las 10–11 h (~50/h). La ocupación pico se da martes y miércoles a las 15–17 h (~265 pacientes): un desfase de ~5 h entre llegada y pico | `03_heatmaps_llegadas_ocupacion.png` | Reforzar el personal de 10 a 18 h de lunes a viernes; programar las altas hospitalarias antes del mediodía | 03 |
| 5 | **Traslados entre áreas = estancia prolongada** | En el modelo explicativo (AUC **0,80**), el nº de áreas de urgencias por las que pasa el paciente es la variable más importante (SHAP 0,88), seguida de nº de laboratorios y procedimientos | `04_shap_prolongada_explicativo.png` | Reducir traslados internos (asignar área definitiva desde el triage) | 04 |
| 6 | **La necesidad de hospitalización se puede anticipar al ingreso** | Modelo con las primeras 2 h: AUC **0,77** (prevalencia 7,6 %). Variables clave: nº de diagnósticos en 2 h, área de entrada, reconsulta reciente, laboratorios tempranos, edad | `04_shap_*` | Alerta temprana para que hospitalización prepare la cama horas antes | 04 |
| 7 | **La estancia prolongada NO se puede predecir bien solo con datos del ingreso** | AUC **0,60** al ingreso vs 0,80 con todo el episodio: la demora se explica por lo que pasa dentro de urgencias, no por el perfil del paciente | `04_shap_prolongada_ingreso.png` | Enfocar la mejora en procesos (laboratorios, traslados, camas), no en "tipos de paciente" | 04 |
| 8 | **Diagnósticos con estancias largas en urgencias** | Infección urinaria 11,5 h, celulitis 11,3 h, cólico renal 9,3 h, dengue 8,1 h, dolor torácico 8,0 h (mediana) | tabla `perfil_dx` | Rutas clínicas rápidas para estos 5 diagnósticos | 04 |
| 9 | **La demanda diaria se puede pronosticar con ~14 % de error** | Pronóstico a 1 día con Holt-Winters: MAPE **13,6 %** (MAE 52 llegadas/día) vs 17,9 % del modelo ingenuo. Alerta de saturación (pico > 316 pacientes): AUC **0,92** | `05_pronostico_llegadas.png` | Tablero diario con el pronóstico y un semáforo de saturación | 05 |
| 10 | **La hospitalización opera al límite: pequeños cambios tienen efecto grande** | Simulación calibrada (≈273 camas efectivas, utilización ~99 %): espera media simulada 13,9 h → **+10 camas: 2,0 h**, **estancia −5 %: 0,9 h**, **alta 4 h antes: 3,0 h**. Con **+10 % de demanda** sin medidas, el sistema colapsa | `06_escenarios.png` | Prioridad 1: gestión de egresos (alta antes del mediodía, sala de egreso). Plan de contingencia para la temporada respiratoria | 06 |

## Problemas de calidad de datos (para el documento)

| Problema | Magnitud | Cómo se manejó |
|---|---|---|
| `visit_occurrence` sin duración (inicio = fin) | 100 % de 1,7 M visitas | Los tiempos se toman de `visit_detail` |
| `visit_occurrence` agrupa etapas separadas por semanas; hay etapas duplicadas en dos visitas | frecuente | Se reconstruyen **episodios** (etapas de la misma persona separadas < 6 h) y se deduplica |
| `visit_detail` con duración 0 | 64 % (sobre todo consultas ambulatorias) | Las consultas ambulatorias se usan solo como antecedente |
| `procedure_date` vacío | 100 % | Los procedimientos se asocian por `visit_occurrence_id` |
| Episodios sin diagnóstico codificado | 76 % | Categoría "Sin diagnóstico codificado"; el diagnóstico solo se usa en el modelo explicativo |
| Laboratorios disponibles | solo el 17 % de los episodios | Se usa el conteo (0 = sin laboratorio) |
| Carga incompleta desde mayo 2026 | caída de 50–70 % en todas las tablas | El análisis se corta el 30-abr-2026 |
| Estancias atípicas (urgencias > 72 h o > 60 días) | 1,5 % de los episodios | Se marcan con `los_atipica` y se excluyen de modelos y gráficos |
| `provider_id` | un solo valor | No se usa |

## Supuestos y limitaciones

- Los nombres de las etapas (triage, atención en urgencias, hospitalización) son interpretación de los conceptos
  OMOP 9203, 3045729 y 9201: **validar con el hospital**.
- No hay dato oficial de camas. La capacidad de la simulación es una *capacidad efectiva* calibrada para reproducir
  la espera observada. Los resultados sirven para **comparar escenarios**, no son una predicción exacta.
- La ocupación de urgencias recorta las etapas de más de 72 h (probables registros sin cierre).
