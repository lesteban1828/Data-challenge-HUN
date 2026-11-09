-- =====================================================================
-- Consultas de RESUMEN para DBeaver (se ejecutan en el servidor, solo devuelven agregados)
-- Base: uhn_i · esquema uninorte_omop · solo lectura (no se pueden crear tablas)
-- Generado desde src/extract.py: episodios de urgencias reconstruidos desde visit_detail.
-- Cada consulta repite el bloque WITH porque la BD no permite tablas temporales.
-- =====================================================================

-- 1. Volumen y estancia por tipo de episodio
WITH st AS (
    SELECT DISTINCT ON (v.person_id, d.visit_detail_concept_id, d.visit_detail_start_datetime,
                        d.visit_detail_end_datetime)
           v.person_id, d.visit_detail_id, d.visit_occurrence_id,
           d.visit_detail_concept_id AS concept_id,
           d.visit_detail_start_datetime AS s,
           GREATEST(COALESCE(d.visit_detail_end_datetime, d.visit_detail_start_datetime),
                    d.visit_detail_start_datetime) AS e,
           (d.visit_detail_end_datetime IS NULL) AS fin_nulo,
           (d.visit_detail_end_datetime < d.visit_detail_start_datetime) AS fin_antes_inicio
    FROM uninorte_omop.visit_detail d
    JOIN uninorte_omop.visit_occurrence v USING (visit_occurrence_id)
    WHERE d.visit_detail_concept_id IN (9203,3045729,9201)
      AND d.visit_detail_start_datetime >= '2023-01-01'
      AND d.visit_detail_start_datetime <  '2026-05-01'
    ORDER BY v.person_id, d.visit_detail_concept_id, d.visit_detail_start_datetime,
             d.visit_detail_end_datetime, d.visit_detail_id
),
st_a AS (
    SELECT st.*, MAX(e) OVER (PARTITION BY person_id ORDER BY s, e, visit_detail_id
                              ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_max_e
    FROM st
),
st2 AS (
    SELECT *, person_id::bigint * 1000
              + SUM(CASE WHEN prev_max_e IS NULL OR s > prev_max_e + INTERVAL '6 hours'
                         THEN 1 ELSE 0 END) OVER (PARTITION BY person_id ORDER BY s, e, visit_detail_id)
              AS episodio_id
    FROM st_a
),
ep AS MATERIALIZED (
    SELECT episodio_id, person_id,
           MIN(s) AS inicio, MAX(e) AS fin, COUNT(*) AS n_etapas,
           BOOL_OR(concept_id = 9201) AS hospitalizado,
           BOOL_OR(concept_id = 9203) AS paso_triage,
           SUM(CASE WHEN concept_id = 9203 THEN EXTRACT(EPOCH FROM e - s) END) / 3600 AS h_triage,
           SUM(CASE WHEN concept_id = 3045729 THEN EXTRACT(EPOCH FROM e - s) END) / 3600 AS h_atencion_urg,
           SUM(CASE WHEN concept_id = 9201 THEN EXTRACT(EPOCH FROM e - s) END) / 3600 AS h_hospitalizacion,
           COUNT(*) FILTER (WHERE concept_id = 3045729) AS n_areas_urg,
           MIN(s) FILTER (WHERE concept_id = 9201) AS inicio_hosp,
           (ARRAY_AGG(concept_id ORDER BY s, e))[1] AS primera_etapa,
           STRING_AGG(concept_id::text, '>' ORDER BY s, e) AS secuencia,
           BOOL_OR(fin_nulo) AS algun_fin_nulo
    FROM st2 GROUP BY episodio_id, person_id
)
SELECT CASE WHEN primera_etapa = 9201 THEN 'Hospitalización directa'
            WHEN hospitalizado THEN 'Urgencias -> Hospitalización'
            WHEN fin - inicio < INTERVAL '15 min' THEN 'Urgencias breve (<15 min)'
            ELSE 'Urgencias con observación' END AS tipo,
       COUNT(*) AS episodios,
       PERCENTILE_CONT(.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM fin - inicio)/3600) AS estancia_p50_h,
       PERCENTILE_CONT(.9) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM fin - inicio)/3600) AS estancia_p90_h
FROM ep GROUP BY 1 ORDER BY 2 DESC;

-- 2. Espera en urgencias antes de hospitalización, por mes
WITH st AS (
    SELECT DISTINCT ON (v.person_id, d.visit_detail_concept_id, d.visit_detail_start_datetime,
                        d.visit_detail_end_datetime)
           v.person_id, d.visit_detail_id, d.visit_occurrence_id,
           d.visit_detail_concept_id AS concept_id,
           d.visit_detail_start_datetime AS s,
           GREATEST(COALESCE(d.visit_detail_end_datetime, d.visit_detail_start_datetime),
                    d.visit_detail_start_datetime) AS e,
           (d.visit_detail_end_datetime IS NULL) AS fin_nulo,
           (d.visit_detail_end_datetime < d.visit_detail_start_datetime) AS fin_antes_inicio
    FROM uninorte_omop.visit_detail d
    JOIN uninorte_omop.visit_occurrence v USING (visit_occurrence_id)
    WHERE d.visit_detail_concept_id IN (9203,3045729,9201)
      AND d.visit_detail_start_datetime >= '2023-01-01'
      AND d.visit_detail_start_datetime <  '2026-05-01'
    ORDER BY v.person_id, d.visit_detail_concept_id, d.visit_detail_start_datetime,
             d.visit_detail_end_datetime, d.visit_detail_id
),
st_a AS (
    SELECT st.*, MAX(e) OVER (PARTITION BY person_id ORDER BY s, e, visit_detail_id
                              ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_max_e
    FROM st
),
st2 AS (
    SELECT *, person_id::bigint * 1000
              + SUM(CASE WHEN prev_max_e IS NULL OR s > prev_max_e + INTERVAL '6 hours'
                         THEN 1 ELSE 0 END) OVER (PARTITION BY person_id ORDER BY s, e, visit_detail_id)
              AS episodio_id
    FROM st_a
),
ep AS MATERIALIZED (
    SELECT episodio_id, person_id,
           MIN(s) AS inicio, MAX(e) AS fin, COUNT(*) AS n_etapas,
           BOOL_OR(concept_id = 9201) AS hospitalizado,
           BOOL_OR(concept_id = 9203) AS paso_triage,
           SUM(CASE WHEN concept_id = 9203 THEN EXTRACT(EPOCH FROM e - s) END) / 3600 AS h_triage,
           SUM(CASE WHEN concept_id = 3045729 THEN EXTRACT(EPOCH FROM e - s) END) / 3600 AS h_atencion_urg,
           SUM(CASE WHEN concept_id = 9201 THEN EXTRACT(EPOCH FROM e - s) END) / 3600 AS h_hospitalizacion,
           COUNT(*) FILTER (WHERE concept_id = 3045729) AS n_areas_urg,
           MIN(s) FILTER (WHERE concept_id = 9201) AS inicio_hosp,
           (ARRAY_AGG(concept_id ORDER BY s, e))[1] AS primera_etapa,
           STRING_AGG(concept_id::text, '>' ORDER BY s, e) AS secuencia,
           BOOL_OR(fin_nulo) AS algun_fin_nulo
    FROM st2 GROUP BY episodio_id, person_id
)
SELECT date_trunc('month', inicio)::date AS mes, COUNT(*) AS episodios,
       PERCENTILE_CONT(.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM inicio_hosp - inicio)/3600) AS espera_p50_h,
       PERCENTILE_CONT(.9) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM inicio_hosp - inicio)/3600) AS espera_p90_h
FROM ep WHERE hospitalizado AND primera_etapa <> 9201 GROUP BY 1 ORDER BY 1;

-- 3. Llegadas por hora del día y día de la semana
WITH st AS (
    SELECT DISTINCT ON (v.person_id, d.visit_detail_concept_id, d.visit_detail_start_datetime,
                        d.visit_detail_end_datetime)
           v.person_id, d.visit_detail_id, d.visit_occurrence_id,
           d.visit_detail_concept_id AS concept_id,
           d.visit_detail_start_datetime AS s,
           GREATEST(COALESCE(d.visit_detail_end_datetime, d.visit_detail_start_datetime),
                    d.visit_detail_start_datetime) AS e,
           (d.visit_detail_end_datetime IS NULL) AS fin_nulo,
           (d.visit_detail_end_datetime < d.visit_detail_start_datetime) AS fin_antes_inicio
    FROM uninorte_omop.visit_detail d
    JOIN uninorte_omop.visit_occurrence v USING (visit_occurrence_id)
    WHERE d.visit_detail_concept_id IN (9203,3045729,9201)
      AND d.visit_detail_start_datetime >= '2023-01-01'
      AND d.visit_detail_start_datetime <  '2026-05-01'
    ORDER BY v.person_id, d.visit_detail_concept_id, d.visit_detail_start_datetime,
             d.visit_detail_end_datetime, d.visit_detail_id
),
st_a AS (
    SELECT st.*, MAX(e) OVER (PARTITION BY person_id ORDER BY s, e, visit_detail_id
                              ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_max_e
    FROM st
),
st2 AS (
    SELECT *, person_id::bigint * 1000
              + SUM(CASE WHEN prev_max_e IS NULL OR s > prev_max_e + INTERVAL '6 hours'
                         THEN 1 ELSE 0 END) OVER (PARTITION BY person_id ORDER BY s, e, visit_detail_id)
              AS episodio_id
    FROM st_a
),
ep AS MATERIALIZED (
    SELECT episodio_id, person_id,
           MIN(s) AS inicio, MAX(e) AS fin, COUNT(*) AS n_etapas,
           BOOL_OR(concept_id = 9201) AS hospitalizado,
           BOOL_OR(concept_id = 9203) AS paso_triage,
           SUM(CASE WHEN concept_id = 9203 THEN EXTRACT(EPOCH FROM e - s) END) / 3600 AS h_triage,
           SUM(CASE WHEN concept_id = 3045729 THEN EXTRACT(EPOCH FROM e - s) END) / 3600 AS h_atencion_urg,
           SUM(CASE WHEN concept_id = 9201 THEN EXTRACT(EPOCH FROM e - s) END) / 3600 AS h_hospitalizacion,
           COUNT(*) FILTER (WHERE concept_id = 3045729) AS n_areas_urg,
           MIN(s) FILTER (WHERE concept_id = 9201) AS inicio_hosp,
           (ARRAY_AGG(concept_id ORDER BY s, e))[1] AS primera_etapa,
           STRING_AGG(concept_id::text, '>' ORDER BY s, e) AS secuencia,
           BOOL_OR(fin_nulo) AS algun_fin_nulo
    FROM st2 GROUP BY episodio_id, person_id
)
SELECT EXTRACT(ISODOW FROM inicio) AS dia_semana, EXTRACT(HOUR FROM inicio) AS hora, COUNT(*) AS llegadas
FROM ep GROUP BY 1, 2 ORDER BY 1, 2;

-- 4. Trayectorias (secuencias de etapas) más frecuentes
WITH st AS (
    SELECT DISTINCT ON (v.person_id, d.visit_detail_concept_id, d.visit_detail_start_datetime,
                        d.visit_detail_end_datetime)
           v.person_id, d.visit_detail_id, d.visit_occurrence_id,
           d.visit_detail_concept_id AS concept_id,
           d.visit_detail_start_datetime AS s,
           GREATEST(COALESCE(d.visit_detail_end_datetime, d.visit_detail_start_datetime),
                    d.visit_detail_start_datetime) AS e,
           (d.visit_detail_end_datetime IS NULL) AS fin_nulo,
           (d.visit_detail_end_datetime < d.visit_detail_start_datetime) AS fin_antes_inicio
    FROM uninorte_omop.visit_detail d
    JOIN uninorte_omop.visit_occurrence v USING (visit_occurrence_id)
    WHERE d.visit_detail_concept_id IN (9203,3045729,9201)
      AND d.visit_detail_start_datetime >= '2023-01-01'
      AND d.visit_detail_start_datetime <  '2026-05-01'
    ORDER BY v.person_id, d.visit_detail_concept_id, d.visit_detail_start_datetime,
             d.visit_detail_end_datetime, d.visit_detail_id
),
st_a AS (
    SELECT st.*, MAX(e) OVER (PARTITION BY person_id ORDER BY s, e, visit_detail_id
                              ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_max_e
    FROM st
),
st2 AS (
    SELECT *, person_id::bigint * 1000
              + SUM(CASE WHEN prev_max_e IS NULL OR s > prev_max_e + INTERVAL '6 hours'
                         THEN 1 ELSE 0 END) OVER (PARTITION BY person_id ORDER BY s, e, visit_detail_id)
              AS episodio_id
    FROM st_a
),
ep AS MATERIALIZED (
    SELECT episodio_id, person_id,
           MIN(s) AS inicio, MAX(e) AS fin, COUNT(*) AS n_etapas,
           BOOL_OR(concept_id = 9201) AS hospitalizado,
           BOOL_OR(concept_id = 9203) AS paso_triage,
           SUM(CASE WHEN concept_id = 9203 THEN EXTRACT(EPOCH FROM e - s) END) / 3600 AS h_triage,
           SUM(CASE WHEN concept_id = 3045729 THEN EXTRACT(EPOCH FROM e - s) END) / 3600 AS h_atencion_urg,
           SUM(CASE WHEN concept_id = 9201 THEN EXTRACT(EPOCH FROM e - s) END) / 3600 AS h_hospitalizacion,
           COUNT(*) FILTER (WHERE concept_id = 3045729) AS n_areas_urg,
           MIN(s) FILTER (WHERE concept_id = 9201) AS inicio_hosp,
           (ARRAY_AGG(concept_id ORDER BY s, e))[1] AS primera_etapa,
           STRING_AGG(concept_id::text, '>' ORDER BY s, e) AS secuencia,
           BOOL_OR(fin_nulo) AS algun_fin_nulo
    FROM st2 GROUP BY episodio_id, person_id
)
SELECT secuencia, COUNT(*) AS episodios FROM ep GROUP BY 1 ORDER BY 2 DESC LIMIT 25;
