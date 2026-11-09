"""Carga de las tablas resumidas (generadas por `python -m src.extract`) con variables derivadas.

    from src import datos
    et = datos.etapas()       # una fila por etapa, con nombre y duración
    ep = datos.episodios()    # una fila por episodio de urgencias, lista para análisis/modelo
"""
from functools import lru_cache

import numpy as np
import pandas as pd

from .config import DATA_INTERIM, ETAPAS, GENDER_CONCEPTS
from . import flow


def _read(name: str) -> pd.DataFrame:
    path = DATA_INTERIM / f"{name}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"No existe {path}. Correr primero: python -m src.extract")
    return pd.read_parquet(path)


@lru_cache(maxsize=1)
def conceptos() -> dict:
    c = _read("conceptos")
    return dict(zip(c.concept_id, c.concept_name))


def etapas() -> pd.DataFrame:
    et = _read("etapas")
    et["etapa"] = et["concept_id"].map(ETAPAS)
    et["duracion_h"] = (et["fin"] - et["inicio"]).dt.total_seconds() / 3600
    g = et.groupby("episodio_id", sort=False)
    et["orden"] = g.cumcount() + 1
    et["espera_previa_h"] = (et["inicio"] - g["fin"].shift()).dt.total_seconds() / 3600
    et["etapa_anterior"] = g["etapa"].shift().fillna("INICIO")
    et["etapa_siguiente"] = g["etapa"].shift(-1).fillna("FIN")
    return et


def censo_urgencias(et: pd.DataFrame, freq: str = "h", max_h: float = 72) -> pd.DataFrame:
    """Pacientes presentes en urgencias (triage + atención) por hora.

    Etapas de urgencias de más de `max_h` horas se recortan (probables registros sin cierre)."""
    urg = et[et["concept_id"].isin([9203, 3045729])].copy()
    urg["fin"] = urg["fin"].clip(upper=urg["inicio"] + pd.Timedelta(hours=max_h))
    # un paciente cuenta una vez aunque tenga dos áreas superpuestas: se usa el episodio
    span = urg.groupby("episodio_id").agg(inicio=("inicio", "min"), fin=("fin", "max"))
    return flow.census(span, "inicio", "fin", freq=freq)


def episodios(et: pd.DataFrame | None = None) -> pd.DataFrame:
    ep = _read("episodios")
    names = conceptos()
    ep["los_h"] = (ep["fin"] - ep["inicio"]).dt.total_seconds() / 3600
    ep["log_los"] = np.log1p(ep["los_h"])
    ep["edad"] = ep["inicio"].dt.year - ep["year_of_birth"]
    ep.loc[(ep["edad"] < 0) | (ep["edad"] > 110), "edad"] = np.nan
    ep["grupo_edad"] = pd.cut(ep["edad"], [-1, 4, 17, 29, 44, 59, 74, 200],
                              labels=["0-4", "5-17", "18-29", "30-44", "45-59", "60-74", "75+"])
    ep["sexo"] = ep["gender_concept_id"].map(GENDER_CONCEPTS).fillna("ND")
    ep["hora_llegada"] = ep["inicio"].dt.hour
    ep["dia_semana"] = ep["inicio"].dt.dayofweek
    ep["mes"] = ep["inicio"].dt.month
    ep["anio"] = ep["inicio"].dt.year
    ep["fin_de_semana"] = (ep["dia_semana"] >= 5).astype(int)
    ep["franja"] = pd.cut(ep["hora_llegada"], [-1, 5, 11, 17, 23],
                          labels=["Madrugada", "Mañana", "Tarde", "Noche"])
    import holidays
    co = holidays.Colombia(years=range(2022, 2028))
    ep["festivo"] = ep["inicio"].dt.date.map(lambda d: d in co).astype(int)

    ep = ep.sort_values(["person_id", "inicio"]).reset_index(drop=True)
    ep["episodios_previos"] = ep.groupby("person_id").cumcount()
    ep["h_desde_episodio_previo"] = (ep["inicio"] - ep["fin_episodio_previo"]).dt.total_seconds() / 3600
    ep["reconsulta_previa_30d"] = (ep["h_desde_episodio_previo"] <= 720).astype(int)
    h_sig = (ep["inicio_episodio_siguiente"] - ep["fin"]).dt.total_seconds() / 3600
    ep["reconsulta_72h"] = (h_sig <= 72).astype(int)
    ep["h_hasta_hosp"] = (ep["inicio_hosp"] - ep["inicio"]).dt.total_seconds() / 3600
    ep["h_hasta_primer_lab"] = (ep["primer_lab"] - ep["inicio"]).dt.total_seconds() / 3600
    # Procedimientos: procedure_date está vacío en la BD → se suman por las visitas del episodio
    if et is None:
        et = etapas()
    pv = DATA_INTERIM / "proc_por_visita.parquet"
    ep = ep.drop(columns=["n_proc"], errors="ignore")
    if pv.exists():
        vis = et[["episodio_id", "visit_occurrence_id"]].drop_duplicates()
        n_proc = vis.merge(pd.read_parquet(pv), on="visit_occurrence_id").groupby("episodio_id")["n_proc"].sum()
        ep["n_proc"] = ep["episodio_id"].map(n_proc)
    else:
        ep["n_proc"] = np.nan
    for c in ["n_labs", "n_labs_2h", "n_tipos_lab", "n_dx", "n_dx_2h", "n_proc", "n_consultas_amb_30d"]:
        ep[c] = ep[c].fillna(0)
    ep.loc[ep["dx_principal"] == 0, "dx_principal"] = np.nan   # 0 = "No matching concept"
    ep["dx_principal_nombre"] = ep["dx_principal"].map(names).fillna("Sin diagnóstico codificado")
    ep["primera_etapa_nombre"] = ep["primera_etapa"].map(ETAPAS)
    ep["tipo_episodio"] = np.where(ep["hospitalizado"], "Urgencias → Hospitalización", "Solo urgencias")
    ep.loc[ep["primera_etapa"] == 9201, "tipo_episodio"] = "Hospitalización directa"
    # Urgencias sin hospitalización: ~60% dura < 15 min (registro/triage o atención breve)
    ep["atencion_breve"] = ((ep["tipo_episodio"] == "Solo urgencias") & (ep["los_h"] < 0.25)).astype(int)
    ep["tipo_detalle"] = ep["tipo_episodio"].where(
        ep["tipo_episodio"] != "Solo urgencias",
        np.where(ep["atencion_breve"] == 1, "Urgencias breve (<15 min)", "Urgencias con observación"))

    # Estancias atípicas (probables etapas sin cierre): urgencias > 72 h o cualquier episodio > 60 días
    ep["los_atipica"] = (((ep["tipo_episodio"] == "Solo urgencias") & (ep["los_h"] > 72))
                         | (ep["los_h"] > 24 * 60)).astype(int)

    # Congestión al llegar: pacientes en urgencias y llegadas en las 6 h previas
    occ = censo_urgencias(et).set_index("fecha_hora")["ocupacion"]
    hora = ep["inicio"].dt.floor("h")
    ep["ocupacion_urg_llegada"] = hora.map(occ).astype(float)
    arr = ep.groupby(hora).size()
    arr = arr.reindex(pd.date_range(arr.index.min(), arr.index.max(), freq="h"), fill_value=0)
    ep["llegadas_ult_6h"] = hora.map(arr.rolling(6, min_periods=1).sum()).astype(float)
    return ep.sort_values("inicio").reset_index(drop=True)


# Variables disponibles AL INGRESO (sin fuga de información) y para el modelo EXPLICATIVO
FEATURES_INGRESO = [
    "edad", "sexo", "hora_llegada", "dia_semana", "mes", "fin_de_semana", "festivo",
    "episodios_previos", "h_desde_episodio_previo", "reconsulta_previa_30d", "n_consultas_amb_30d",
    "ocupacion_urg_llegada", "llegadas_ult_6h", "n_labs_2h", "n_dx_2h", "primera_etapa_nombre",
]
FEATURES_EXPLICATIVO = FEATURES_INGRESO + [
    "n_labs", "n_tipos_lab", "n_dx", "n_proc", "n_areas_urg", "dx_principal_nombre",
]
