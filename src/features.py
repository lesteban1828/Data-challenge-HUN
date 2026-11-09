"""Construcción de la tabla analítica a nivel de visita."""
import numpy as np
import pandas as pd

from .config import DATA_PROCESSED, GENDER_CONCEPTS, VISIT_CONCEPTS
from . import flow

VS, VE = "visit_start_datetime", "visit_end_datetime"


def _count_by_visit(df: pd.DataFrame | None, name: str, time_col: str | None = None,
                    visits: pd.DataFrame | None = None, hours: float | None = None) -> pd.Series:
    """Conteo de registros por visita. Si `hours` se da, solo cuenta los ocurridos
    dentro de las primeras `hours` horas de la visita (evita fuga de información)."""
    if df is None:
        return pd.Series(dtype=float, name=name)
    d = df
    if hours is not None and time_col and visits is not None:
        d = d.merge(visits[["visit_occurrence_id", VS]], on="visit_occurrence_id", how="inner")
        d = d[(d[time_col] - d[VS]) <= pd.Timedelta(hours=hours)]
    return d.groupby("visit_occurrence_id").size().rename(name)


def build_visit_table(t: dict[str, pd.DataFrame], early_hours: float = 2.0) -> pd.DataFrame:
    """Tabla una-fila-por-visita con target (LOS) y variables explicativas.

    - Variables *_total: usan toda la visita → solo para el modelo EXPLICATIVO.
    - Variables *_tempranas: primeras `early_hours` horas → aptas para el modelo AL INGRESO.
    """
    vo = t["visit_occurrence"].dropna(subset=[VS]).copy()

    # Target
    vo["los_h"] = (vo[VE] - vo[VS]).dt.total_seconds() / 3600
    vo = vo[vo["los_h"].isna() | (vo["los_h"] >= 0)]
    vo["log_los"] = np.log1p(vo["los_h"])

    # Paciente
    if "person" in t:
        p = t["person"][["person_id", "gender_concept_id", "year_of_birth"]]
        vo = vo.merge(p, on="person_id", how="left")
        vo["edad"] = vo[VS].dt.year - vo["year_of_birth"]
        vo["sexo"] = vo["gender_concept_id"].map(GENDER_CONCEPTS).fillna("Otro/ND")

    # Visita y calendario
    names = dict(VISIT_CONCEPTS)
    cm_path = DATA_PROCESSED / "concept_map.csv"
    if cm_path.exists():  # nombres reales desde la tabla CONCEPT (db.concept_map)
        names.update(pd.read_csv(cm_path).set_index("concept_id")["concept_name"].to_dict())
    vo["tipo_visita"] = vo["visit_concept_id"].map(names).fillna(vo["visit_concept_id"].astype(str))
    vo["hora_llegada"] = vo[VS].dt.hour
    vo["dia_semana"] = vo[VS].dt.dayofweek
    vo["mes"] = vo[VS].dt.month
    vo["fin_de_semana"] = (vo["dia_semana"] >= 5).astype(int)
    vo["franja"] = pd.cut(vo["hora_llegada"], [-1, 5, 11, 17, 23],
                          labels=["Madrugada", "Mañana", "Tarde", "Noche"])
    try:
        import holidays
        co = holidays.Colombia(years=range(vo[VS].dt.year.min(), vo[VS].dt.year.max() + 1))
        vo["festivo"] = vo[VS].dt.date.map(lambda d: d in co).astype(int)
    except ImportError:
        pass

    # Historia del paciente
    vo = vo.sort_values(["person_id", VS])
    vo["visitas_previas"] = vo.groupby("person_id").cumcount()
    prev_end = vo.groupby("person_id")[VE].shift()
    vo["horas_desde_visita_previa"] = (vo[VS] - prev_end).dt.total_seconds() / 3600
    vo["reingreso_30d"] = (vo["horas_desde_visita_previa"] <= 30 * 24).astype(int)
    vo["tiene_visita_precedente"] = vo["preceding_visit_occurrence_id"].notna().astype(int) \
        if "preceding_visit_occurrence_id" in vo else 0

    # Congestión (variable de cola): ocupación y llegadas al momento de llegar
    occ = flow.census(vo, VS, VE, freq="h")
    vo["ocupacion_llegada"] = flow.occupancy_at_arrival(vo, occ)
    arr = flow.arrivals(vo, VS, freq="h").set_index("fecha_hora")["llegadas"]
    arr6 = arr.rolling(6, min_periods=1).sum()
    vo["llegadas_ultimas_6h"] = vo[VS].dt.floor("h").map(arr6).astype(float)

    # Complejidad clínica
    conds, procs, meas = t.get("condition_occurrence"), t.get("procedure_occurrence"), t.get("measurement")
    counts = [
        _count_by_visit(conds, "n_diagnosticos_total"),
        _count_by_visit(procs, "n_procedimientos_total"),
        _count_by_visit(meas, "n_mediciones_total"),
        _count_by_visit(conds, "n_diagnosticos_tempranos", "condition_start_datetime", vo, early_hours),
        _count_by_visit(procs, "n_procedimientos_tempranos", "procedure_datetime", vo, early_hours),
        _count_by_visit(meas, "n_mediciones_tempranas", "measurement_datetime", vo, early_hours),
    ]
    if "visit_detail" in t:
        counts.append(t["visit_detail"].groupby("visit_occurrence_id").size().rename("n_etapas"))
    for s in counts:
        if len(s):
            vo = vo.merge(s, left_on="visit_occurrence_id", right_index=True, how="left")
            vo[s.name] = vo[s.name].fillna(0)

    # Diagnóstico principal (el primero registrado) como categoría
    if conds is not None and "condition_start_datetime" in conds:
        first = (conds.sort_values("condition_start_datetime")
                      .groupby("visit_occurrence_id")["condition_concept_id"].first()
                      .rename("dx_principal"))
        vo = vo.merge(first, left_on="visit_occurrence_id", right_index=True, how="left")

    # Estancia prolongada: > P75 dentro de su tipo de visita
    p75 = vo.groupby("tipo_visita")["los_h"].transform(lambda x: x.quantile(0.75))
    vo["estancia_prolongada"] = (vo["los_h"] > p75).astype(int)
    return vo.reset_index(drop=True)


# Conjuntos de variables para cada versión del modelo
FEATURES_INGRESO = [
    "edad", "sexo", "tipo_visita", "visit_type_concept_id", "hora_llegada", "dia_semana", "mes",
    "fin_de_semana", "festivo", "visitas_previas", "horas_desde_visita_previa", "reingreso_30d",
    "tiene_visita_precedente", "ocupacion_llegada", "llegadas_ultimas_6h",
    "n_diagnosticos_tempranos", "n_procedimientos_tempranos", "n_mediciones_tempranas",
]
FEATURES_EXPLICATIVO = FEATURES_INGRESO + [
    "n_diagnosticos_total", "n_procedimientos_total", "n_mediciones_total", "n_etapas", "dx_principal",
]
