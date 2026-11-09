# Diccionario de datos (OMOP CDM)

## Relaciones

```
PERSON (person_id)
  └── VISIT_OCCURRENCE (visit_occurrence_id, person_id, preceding_visit_occurrence_id)
        ├── VISIT_DETAIL (visit_detail_id, visit_occurrence_id)        ← etapas del flujo
        ├── CONDITION_OCCURRENCE (visit_occurrence_id, person_id)      ← diagnósticos
        ├── PROCEDURE_OCCURRENCE (visit_occurrence_id, person_id)      ← procedimientos
        └── MEASUREMENT (visit_occurrence_id, person_id)               ← laboratorios / signos
```

## Tablas

| Tabla | Variable | Uso en el análisis |
|---|---|---|
| PERSON | person_id, gender_concept_id, year_of_birth, race_concept_id, ethnicity_concept_id | Edad al momento de la visita, sexo |
| VISIT_OCCURRENCE | visit_occurrence_id, person_id, visit_concept_id, visit_start_datetime, visit_end_datetime, visit_type_concept_id, provider_id, preceding_visit_occurrence_id | Unidad principal: LOS, tipo de visita, llegadas, reingresos |
| VISIT_DETAIL | visit_detail_id, visit_occurrence_id, visit_detail_concept_id, visit_detail_start_datetime, visit_detail_end_datetime, provider_id | Event log: etapas, duraciones, esperas entre etapas |
| CONDITION_OCCURRENCE | condition_occurrence_id, person_id, visit_occurrence_id, condition_concept_id, condition_start_datetime, condition_type_concept_id | Complejidad diagnóstica, diagnóstico principal |
| PROCEDURE_OCCURRENCE | procedure_occurrence_id, person_id, visit_occurrence_id, procedure_concept_id, procedure_datetime, procedure_type_concept_id | Complejidad, procedimientos que alargan la estancia |
| MEASUREMENT | measurement_id, person_id, visit_occurrence_id, measurement_concept_id, measurement_datetime, value_as_number, unit_concept_id, measurement_type_concept_id | Intensidad diagnóstica, tiempos hasta resultados |

## Conceptos OMOP frecuentes (verificar con los datos)

| Campo | concept_id | Significado |
|---|---|---|
| visit_concept_id | 9201 | Inpatient Visit (hospitalización) |
| visit_concept_id | 9202 | Outpatient Visit (ambulatoria) |
| visit_concept_id | 9203 | Emergency Room Visit (urgencias) |
| visit_concept_id | 262 | Emergency Room and Inpatient Visit |
| visit_detail_concept_id | 32037 | Intensive Care (UCI) |
| gender_concept_id | 8507 | Male |
| gender_concept_id | 8532 | Female |

Para el resto de IDs: pedir la tabla `CONCEPT` a los organizadores o buscarlos en https://athena.ohdsi.org.
Registrar los mapeos en `data/processed/concept_map.csv` (columnas: `concept_id, concept_name, domain`).
