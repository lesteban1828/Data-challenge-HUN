"""Extracción resumida desde la BD del reto: TODO el trabajo pesado se hace en el servidor.

Al computador solo llegan tablas ya preparadas (guardadas en DATA_DIR, en el disco D:):

  etapas.parquet      una fila por etapa de urgencias/hospitalización (deduplicada) con su episodio
  episodios.parquet   una fila por episodio de urgencias con variables clínicas resumidas
  conceptos.parquet   nombres de los diagnósticos / laboratorios que aparecen
  mensual_tablas.parquet  conteos mensuales por tabla (calidad de datos)
  top_dx.parquet, top_labs.parquet  rankings agregados

Episodio = cadena de etapas (triage 9203, atención urgencias 3045729, hospitalización 9201) de una
misma persona con menos de GAP_EPISODIO_H horas entre el fin de una y el inicio de la siguiente.
Se reconstruye así porque en la BD visit_occurrence no tiene duración (inicio = fin) y agrupa
etapas separadas por semanas; además hay etapas duplicadas en dos visitas distintas.

Uso:
    python -m src.extract            # todo
    python -m src.extract --solo episodios
"""
import argparse
import time

import pandas as pd
from sqlalchemy import text

from . import db
from .config import (DATA_INTERIM, ETAPAS_URGENCIAS, FECHA_CORTE, FECHA_INICIO,
                     GAP_EPISODIO_H)

SCHEMA = "uninorte_omop"


def _cte() -> str:
    """CTEs que reconstruyen etapas únicas (st), episodios (st2) y su resumen (ep).

    La BD es de solo lectura (no permite tablas temporales), así que cada consulta las incluye.
    """
    s = SCHEMA
    etapas = ",".join(map(str, ETAPAS_URGENCIAS))
    return f"""
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
    FROM {s}.visit_detail d
    JOIN {s}.visit_occurrence v USING (visit_occurrence_id)
    WHERE d.visit_detail_concept_id IN ({etapas})
      AND d.visit_detail_start_datetime >= '{FECHA_INICIO}'
      AND d.visit_detail_start_datetime <  '{FECHA_CORTE}'
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
              + SUM(CASE WHEN prev_max_e IS NULL OR s > prev_max_e + INTERVAL '{GAP_EPISODIO_H} hours'
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
)"""


Q_ETAPAS = _cte() + """
SELECT episodio_id, person_id, visit_detail_id, visit_occurrence_id, concept_id, s AS inicio, e AS fin,
       fin_nulo, fin_antes_inicio
FROM st2 ORDER BY episodio_id, s, e
"""

Q_EPISODIOS = _cte() + f""",
base AS (
  SELECT ep.*, p.gender_concept_id, p.year_of_birth,
         LAG(fin) OVER w AS fin_episodio_previo,
         LEAD(inicio) OVER w AS inicio_episodio_siguiente
  FROM ep LEFT JOIN {SCHEMA}.person p USING (person_id)
  WINDOW w AS (PARTITION BY person_id ORDER BY inicio)
),
lab AS (
  SELECT ep.episodio_id,
         COUNT(DISTINCT (m.measurement_concept_id, m.measurement_datetime)) AS n_labs,
         COUNT(DISTINCT (m.measurement_concept_id, m.measurement_datetime))
           FILTER (WHERE m.measurement_datetime <= ep.inicio + INTERVAL '2 hours') AS n_labs_2h,
         COUNT(DISTINCT m.measurement_concept_id) AS n_tipos_lab,
         MIN(m.measurement_datetime) AS primer_lab
  FROM ep JOIN {SCHEMA}.measurement m
    ON m.person_id = ep.person_id
   AND m.measurement_datetime BETWEEN ep.inicio AND ep.fin
  GROUP BY ep.episodio_id
),
dx AS (
  SELECT ep.episodio_id,
         COUNT(DISTINCT c.condition_concept_id) AS n_dx,
         COUNT(DISTINCT c.condition_concept_id)
           FILTER (WHERE c.condition_start_datetime <= ep.inicio + INTERVAL '2 hours') AS n_dx_2h,
         (ARRAY_AGG(c.condition_concept_id ORDER BY c.condition_start_datetime, c.condition_occurrence_id))[1] AS dx_principal
  FROM ep JOIN {SCHEMA}.condition_occurrence c
    ON c.person_id = ep.person_id
   AND c.condition_start_datetime BETWEEN ep.inicio - INTERVAL '1 hour' AND ep.fin
  GROUP BY ep.episodio_id
),
pr AS (
  SELECT ep.episodio_id, COUNT(DISTINCT pr.procedure_concept_id) AS n_proc
  FROM ep JOIN {SCHEMA}.procedure_occurrence pr
    ON pr.person_id = ep.person_id
   AND pr.procedure_date BETWEEN ep.inicio::date AND ep.fin::date
  GROUP BY ep.episodio_id
),
amb AS (
  SELECT ep.episodio_id, COUNT(DISTINCT d.visit_detail_start_datetime) AS n_consultas_amb_30d
  FROM ep
  JOIN {SCHEMA}.visit_occurrence v ON v.person_id = ep.person_id
  JOIN {SCHEMA}.visit_detail d ON d.visit_occurrence_id = v.visit_occurrence_id
   AND d.visit_detail_concept_id = 581479
   AND d.visit_detail_start_datetime >= ep.inicio - INTERVAL '30 days'
   AND d.visit_detail_start_datetime <  ep.inicio
  GROUP BY ep.episodio_id
)
SELECT b.*, lab.n_labs, lab.n_labs_2h, lab.n_tipos_lab, lab.primer_lab,
       dx.n_dx, dx.n_dx_2h, dx.dx_principal, pr.n_proc, amb.n_consultas_amb_30d
FROM base b
LEFT JOIN lab USING (episodio_id)
LEFT JOIN dx USING (episodio_id)
LEFT JOIN pr USING (episodio_id)
LEFT JOIN amb USING (episodio_id)
"""

Q_TOP_DX = _cte() + f"""
SELECT c.condition_concept_id AS concept_id, COUNT(DISTINCT ep.episodio_id) AS episodios
FROM ep JOIN {SCHEMA}.condition_occurrence c
  ON c.person_id = ep.person_id AND c.condition_start_datetime BETWEEN ep.inicio - INTERVAL '1 hour' AND ep.fin
GROUP BY 1 ORDER BY 2 DESC LIMIT 300
"""

Q_TOP_LABS = _cte() + f"""
SELECT m.measurement_concept_id AS concept_id, COUNT(*) AS n, COUNT(DISTINCT ep.episodio_id) AS episodios
FROM ep JOIN {SCHEMA}.measurement m
  ON m.person_id = ep.person_id AND m.measurement_datetime BETWEEN ep.inicio AND ep.fin
GROUP BY 1 ORDER BY 2 DESC LIMIT 100
"""

Q_MENSUAL = f"""
SELECT 'visit_occurrence' tabla, date_trunc('month', visit_start_datetime)::date mes, COUNT(*) n FROM {SCHEMA}.visit_occurrence GROUP BY 2
UNION ALL SELECT 'visit_detail_' || visit_detail_concept_id, date_trunc('month', visit_detail_start_datetime)::date, COUNT(*) FROM {SCHEMA}.visit_detail GROUP BY 1, 2
UNION ALL SELECT 'condition_occurrence', date_trunc('month', condition_start_datetime)::date, COUNT(*) FROM {SCHEMA}.condition_occurrence GROUP BY 2
UNION ALL SELECT 'procedure_occurrence', date_trunc('month', procedure_date)::date, COUNT(*) FROM {SCHEMA}.procedure_occurrence GROUP BY 2
UNION ALL SELECT 'measurement', date_trunc('month', measurement_datetime)::date, COUNT(*) FROM {SCHEMA}.measurement GROUP BY 2
"""

Q_CALIDAD = f"""
SELECT 'visit_detail' tabla, COUNT(*) n,
       SUM((visit_detail_end_datetime IS NULL)::int) fin_nulo,
       SUM((visit_detail_end_datetime < visit_detail_start_datetime)::int) fin_antes_inicio,
       SUM((visit_detail_end_datetime = visit_detail_start_datetime)::int) duracion_cero,
       SUM((v.visit_occurrence_id IS NULL)::int) huerfanos
FROM {SCHEMA}.visit_detail d
LEFT JOIN {SCHEMA}.visit_occurrence v USING (visit_occurrence_id)
UNION ALL
SELECT 'visit_occurrence', COUNT(*), SUM((visit_end_datetime IS NULL)::int),
       SUM((visit_end_datetime < visit_start_datetime)::int),
       SUM((visit_end_datetime = visit_start_datetime)::int),
       SUM((p.person_id IS NULL)::int)
FROM {SCHEMA}.visit_occurrence v
LEFT JOIN {SCHEMA}.person p USING (person_id)
"""


# procedure_date viene vacío en toda la tabla → los procedimientos se asocian por visita
Q_PROC_VISITA = f"""
SELECT visit_occurrence_id, COUNT(*) AS n_proc_reg, COUNT(DISTINCT procedure_concept_id) AS n_proc
FROM {SCHEMA}.procedure_occurrence WHERE visit_occurrence_id IS NOT NULL GROUP BY 1
"""


def _read(conn, sql: str) -> pd.DataFrame:
    df = pd.read_sql(text(sql), conn)
    df.columns = [c.lower() for c in df.columns]
    return df


def _save(df: pd.DataFrame, name: str) -> None:
    path = DATA_INTERIM / f"{name}.parquet"
    df.to_parquet(path, index=False)
    print(f"  ✔ {name:<18} {len(df):>10,} filas → {path}")


def run(solo: str | None = None) -> None:
    t0 = time.time()
    with db.engine().connect() as conn:
        conn.execute(text("SET work_mem = '512MB'"))
        if solo in (None, "calidad"):
            print("Calidad y conteos mensuales…")
            _save(_read(conn, Q_MENSUAL), "mensual_tablas")
            _save(_read(conn, Q_CALIDAD), "calidad_intervalos")
        if solo in (None, "calidad", "proc"):
            _save(_read(conn, Q_PROC_VISITA), "proc_por_visita")
        if solo in ("calidad", "proc"):
            return
        print("Etapas y episodios (calculados en el servidor)…")
        _save(_read(conn, Q_ETAPAS), "etapas")
        print("Variables clínicas por episodio (labs, dx, procedimientos)…")
        ep = _read(conn, Q_EPISODIOS)
        _save(ep, "episodios")
        print(f"  ({time.time() - t0:.0f}s)")
        top_dx, top_labs = _read(conn, Q_TOP_DX), _read(conn, Q_TOP_LABS)
        _save(top_dx, "top_dx")
        _save(top_labs, "top_labs")
        ids = set(top_dx.concept_id) | set(top_labs.concept_id) | set(ep.dx_principal.dropna().astype(int))
        ids = ",".join(str(int(i)) for i in ids) or "0"
        _save(_read(conn, f"SELECT concept_id, concept_name, domain_id, vocabulary_id "
                          f"FROM {SCHEMA}.concept WHERE concept_id IN ({ids})"), "conceptos")
    print(f"Listo en {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", choices=["calidad", "episodios", "proc"])
    run(ap.parse_args().solo)
