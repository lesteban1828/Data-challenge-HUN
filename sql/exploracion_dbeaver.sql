-- =====================================================================
-- Exploración inicial en DBeaver — Data Challenge HUN 2026
-- Escrito para PostgreSQL. Si la BD es SQL Server, ver equivalencias al final.
-- Si las tablas están en un esquema, anteponerlo: cdm.visit_occurrence
-- Ejecutar una consulta a la vez: cursor dentro de la consulta + Ctrl+Enter
-- =====================================================================

-- 1. Volumen por tabla
SELECT 'person' AS tabla, COUNT(*) AS filas FROM person
UNION ALL SELECT 'visit_occurrence', COUNT(*) FROM visit_occurrence
UNION ALL SELECT 'visit_detail', COUNT(*) FROM visit_detail
UNION ALL SELECT 'condition_occurrence', COUNT(*) FROM condition_occurrence
UNION ALL SELECT 'procedure_occurrence', COUNT(*) FROM procedure_occurrence
UNION ALL SELECT 'measurement', COUNT(*) FROM measurement;

-- 2. Rango de fechas y visitas abiertas
SELECT MIN(visit_start_datetime) AS desde,
       MAX(visit_start_datetime) AS hasta,
       SUM(CASE WHEN visit_end_datetime IS NULL THEN 1 ELSE 0 END) AS sin_fin,
       SUM(CASE WHEN visit_end_datetime < visit_start_datetime THEN 1 ELSE 0 END) AS fin_antes_inicio
FROM visit_occurrence;

-- 3. ¿Las fechas traen hora real o solo fecha (00:00)?
SELECT ROUND(100.0 * AVG(CASE WHEN CAST(visit_start_datetime AS time) = '00:00:00' THEN 1 ELSE 0 END), 2) AS pct_inicio_medianoche,
       ROUND(100.0 * AVG(CASE WHEN CAST(visit_detail_start_datetime AS time) = '00:00:00' THEN 1 ELSE 0 END), 2) AS pct_etapa_medianoche
FROM visit_occurrence vo
JOIN visit_detail vd USING (visit_occurrence_id);

-- 4. Tipos de visita y etapas (con nombre si existe la tabla CONCEPT)
SELECT vo.visit_concept_id, c.concept_name, COUNT(*) AS n
FROM visit_occurrence vo
LEFT JOIN concept c ON c.concept_id = vo.visit_concept_id
GROUP BY vo.visit_concept_id, c.concept_name
ORDER BY n DESC;

SELECT vd.visit_detail_concept_id, c.concept_name, COUNT(*) AS n
FROM visit_detail vd
LEFT JOIN concept c ON c.concept_id = vd.visit_detail_concept_id
GROUP BY vd.visit_detail_concept_id, c.concept_name
ORDER BY n DESC;

-- 5. Etapas por visita
SELECT n_etapas, COUNT(*) AS visitas
FROM (SELECT visit_occurrence_id, COUNT(*) AS n_etapas FROM visit_detail GROUP BY visit_occurrence_id) x
GROUP BY n_etapas
ORDER BY n_etapas;

-- 6. Ejemplo de trayectoria de 5 visitas (duración y espera entre etapas, en horas)
SELECT vd.visit_occurrence_id,
       ROW_NUMBER() OVER (PARTITION BY vd.visit_occurrence_id ORDER BY vd.visit_detail_start_datetime) AS orden,
       vd.visit_detail_concept_id,
       vd.visit_detail_start_datetime,
       vd.visit_detail_end_datetime,
       ROUND(EXTRACT(EPOCH FROM (vd.visit_detail_end_datetime - vd.visit_detail_start_datetime)) / 3600.0, 2) AS duracion_h,
       ROUND(EXTRACT(EPOCH FROM (vd.visit_detail_start_datetime
             - LAG(vd.visit_detail_end_datetime) OVER (PARTITION BY vd.visit_occurrence_id
                                                       ORDER BY vd.visit_detail_start_datetime))) / 3600.0, 2) AS espera_previa_h
FROM visit_detail vd
WHERE vd.visit_occurrence_id IN (SELECT visit_occurrence_id FROM visit_detail
                                 GROUP BY visit_occurrence_id HAVING COUNT(*) >= 3 LIMIT 5)
ORDER BY vd.visit_occurrence_id, orden;

-- 7. Estancia (LOS) por tipo de visita, en horas
SELECT visit_concept_id,
       COUNT(*) AS n,
       ROUND(AVG(EXTRACT(EPOCH FROM (visit_end_datetime - visit_start_datetime)) / 3600.0)::numeric, 2) AS los_media_h,
       ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (visit_end_datetime - visit_start_datetime)) / 3600.0))::numeric, 2) AS los_p50_h,
       ROUND((PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (visit_end_datetime - visit_start_datetime)) / 3600.0))::numeric, 2) AS los_p90_h
FROM visit_occurrence
WHERE visit_end_datetime >= visit_start_datetime
GROUP BY visit_concept_id
ORDER BY n DESC;

-- 8. Llegadas por hora del día y día de la semana (0 = domingo)
SELECT EXTRACT(DOW FROM visit_start_datetime) AS dia_semana,
       EXTRACT(HOUR FROM visit_start_datetime) AS hora,
       COUNT(*) AS llegadas
FROM visit_occurrence
GROUP BY 1, 2
ORDER BY 1, 2;

-- 9. Integridad: etapas cuya visita no existe
SELECT COUNT(*) AS etapas_huerfanas
FROM visit_detail vd
LEFT JOIN visit_occurrence vo ON vo.visit_occurrence_id = vd.visit_occurrence_id
WHERE vo.visit_occurrence_id IS NULL;

-- =====================================================================
-- Equivalencias SQL Server
--   EXTRACT(EPOCH FROM (b - a)) / 3600.0   ->  DATEDIFF(MINUTE, a, b) / 60.0
--   EXTRACT(HOUR FROM x)                   ->  DATEPART(HOUR, x)
--   EXTRACT(DOW FROM x)                    ->  DATEPART(WEEKDAY, x)
--   ... LIMIT 5                            ->  SELECT TOP 5 ...
--   JOIN ... USING (col)                   ->  JOIN ... ON a.col = b.col
--   PERCENTILE_CONT(...) WITHIN GROUP (...) ->  igual, pero agregar OVER (PARTITION BY visit_concept_id)
-- =====================================================================
