"""Genera datos SINTÉTICOS con el mismo esquema OMOP del reto en data/sample/.

Sirve para probar los notebooks antes de recibir los datos reales.
Uso:  python scripts/generar_datos_sinteticos.py --visitas 5000
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "data" / "sample"

# Etapas ficticias (en el dato real serán visit_detail_concept_id)
ETAPAS = {
    9203: [(1, "Triage", 0.3), (2, "Consulta urgencias", 1.0), (3, "Laboratorio/Imágenes", 2.0),
           (4, "Observación", 6.0)],
    9201: [(5, "Admisión", 0.5), (6, "Hospitalización piso", 72.0), (7, "UCI", 48.0)],
    9202: [(8, "Consulta externa", 0.5), (3, "Laboratorio/Imágenes", 1.0)],
}


def main(n_visits: int, seed: int = 42):
    rng = np.random.default_rng(seed)
    OUT.mkdir(parents=True, exist_ok=True)
    n_persons = n_visits // 2
    person = pd.DataFrame({
        "person_id": np.arange(1, n_persons + 1),
        "gender_concept_id": rng.choice([8507, 8532], n_persons),
        "year_of_birth": rng.integers(1940, 2024, n_persons),
        "race_concept_id": 0, "ethnicity_concept_id": 0,
    })

    # Llegadas con patrón horario (pico 10–14 h) y semanal
    start = pd.Timestamp("2025-01-01")
    hours = rng.choice(24, n_visits, p=np.r_[np.full(7, .015), np.full(5, .07), np.full(6, .055), np.full(6, .02)] /
                       np.r_[np.full(7, .015), np.full(5, .07), np.full(6, .055), np.full(6, .02)].sum())
    days = rng.integers(0, 365, n_visits)
    vstart = start + pd.to_timedelta(days, "D") + pd.to_timedelta(hours, "h") + \
        pd.to_timedelta(rng.integers(0, 60, n_visits), "m")
    vtype = rng.choice([9203, 9201, 9202], n_visits, p=[.55, .15, .30])

    vo_rows, vd_rows, vd_id = [], [], 1
    for i in range(n_visits):
        t = vstart[i]
        congest = 1 + 0.6 * (10 <= t.hour <= 15)
        for concept, _, mean_h in ETAPAS[vtype[i]]:
            if concept == 7 and rng.random() > .2:
                continue  # solo 20% pasa a UCI
            wait = rng.exponential(0.5 * congest)
            s = t + pd.Timedelta(hours=wait)
            e = s + pd.Timedelta(hours=rng.gamma(2, mean_h / 2) * congest)
            vd_rows.append((vd_id, i + 1, concept, s.floor("min"), e.floor("min"), rng.integers(1, 80)))
            vd_id += 1
            t = e
        vo_rows.append((i + 1, rng.integers(1, n_persons + 1), vtype[i], vstart[i], t.floor("min"),
                        32817, rng.integers(1, 80), np.nan))

    vo = pd.DataFrame(vo_rows, columns=["visit_occurrence_id", "person_id", "visit_concept_id",
                                        "visit_start_datetime", "visit_end_datetime",
                                        "visit_type_concept_id", "provider_id",
                                        "preceding_visit_occurrence_id"])
    vd = pd.DataFrame(vd_rows, columns=["visit_detail_id", "visit_occurrence_id", "visit_detail_concept_id",
                                        "visit_detail_start_datetime", "visit_detail_end_datetime",
                                        "provider_id"])

    def child(n_per_visit, cols_fn, name):
        rows = []
        for _, v in vo.iterrows():
            for _ in range(rng.poisson(n_per_visit)):
                dt = v.visit_start_datetime + (v.visit_end_datetime - v.visit_start_datetime) * rng.random()
                rows.append(cols_fn(v, dt))
        df = pd.DataFrame(rows)
        df.insert(0, f"{name}_id", np.arange(1, len(df) + 1))
        return df

    co = child(2, lambda v, dt: dict(person_id=v.person_id, visit_occurrence_id=v.visit_occurrence_id,
                                     condition_concept_id=rng.choice([201826, 316866, 320128, 4329847, 255848]),
                                     condition_start_datetime=dt, condition_type_concept_id=32817),
               "condition_occurrence")
    po = child(1.5, lambda v, dt: dict(person_id=v.person_id, visit_occurrence_id=v.visit_occurrence_id,
                                       procedure_concept_id=rng.choice([4163872, 4301351, 2313814]),
                                       procedure_datetime=dt, procedure_type_concept_id=32817),
               "procedure_occurrence")
    me = child(4, lambda v, dt: dict(person_id=v.person_id, visit_occurrence_id=v.visit_occurrence_id,
                                     measurement_concept_id=rng.choice([3027018, 3004249, 3020891]),
                                     measurement_datetime=dt, value_as_number=round(rng.normal(80, 15), 1),
                                     unit_concept_id=0, measurement_type_concept_id=32817),
               "measurement")

    for name, df in [("person", person), ("visit_occurrence", vo), ("visit_detail", vd),
                     ("condition_occurrence", co), ("procedure_occurrence", po), ("measurement", me)]:
        df.to_csv(OUT / f"{name}.csv", index=False)
        print(f"{name:<22} {len(df):>8,} filas")
    pd.DataFrame([(c, n) for v in ETAPAS.values() for c, n, _ in v], columns=["concept_id", "concept_name"]) \
        .drop_duplicates().to_csv(OUT / "concept_map.csv", index=False)
    print(f"\nDatos sintéticos en {OUT}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--visitas", type=int, default=5000)
    main(ap.parse_args().visitas)
