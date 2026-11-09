"""Chequeos de calidad de datos."""
import pandas as pd


def summary(df: pd.DataFrame) -> pd.DataFrame:
    """Tipo, % nulos y nº de valores únicos por columna."""
    return pd.DataFrame({
        "dtype": df.dtypes.astype(str),
        "pct_nulos": (df.isna().mean() * 100).round(2),
        "n_unicos": df.nunique(),
    })


def check_intervals(df: pd.DataFrame, start: str, end: str) -> dict:
    """Problemas típicos en pares de fechas inicio/fin."""
    dur_h = (df[end] - df[start]).dt.total_seconds() / 3600
    midnight = lambda s: (s.dt.hour.eq(0) & s.dt.minute.eq(0) & s.dt.second.eq(0))
    return {
        "n": len(df),
        "inicio_nulo": int(df[start].isna().sum()),
        "fin_nulo (abiertas)": int(df[end].isna().sum()),
        "fin_antes_de_inicio": int((dur_h < 0).sum()),
        "duracion_cero": int((dur_h == 0).sum()),
        "pct_inicio_00:00": round(midnight(df[start]).mean() * 100, 2),
        "pct_fin_00:00": round(midnight(df[end]).mean() * 100, 2),
        "duracion_h_p50": round(dur_h.median(), 2),
        "duracion_h_p99": round(dur_h.quantile(0.99), 2),
        "fecha_min": df[start].min(),
        "fecha_max": df[start].max(),
    }


def check_foreign_key(child: pd.DataFrame, parent: pd.DataFrame, key: str) -> dict:
    """Registros hijos cuyo id no existe en la tabla padre."""
    orphan = ~child[key].isin(parent[key])
    return {"key": key, "huerfanos": int(orphan.sum()), "pct": round(orphan.mean() * 100, 2)}


def check_duplicates(df: pd.DataFrame, key: str) -> int:
    return int(df[key].duplicated().sum())


def full_report(t: dict[str, pd.DataFrame]) -> dict:
    """Reporte de calidad sobre el diccionario de tablas de load_all()."""
    rep = {}
    if "visit_occurrence" in t:
        vo = t["visit_occurrence"]
        rep["visit_occurrence"] = check_intervals(vo, "visit_start_datetime", "visit_end_datetime")
        rep["visit_occurrence"]["duplicados_id"] = check_duplicates(vo, "visit_occurrence_id")
    if "visit_detail" in t:
        vd = t["visit_detail"]
        rep["visit_detail"] = check_intervals(vd, "visit_detail_start_datetime", "visit_detail_end_datetime")
        if "visit_occurrence" in t:
            rep["visit_detail"]["fk"] = check_foreign_key(vd, t["visit_occurrence"], "visit_occurrence_id")
    for name in ("condition_occurrence", "procedure_occurrence", "measurement"):
        if name in t and "visit_occurrence" in t:
            rep[name] = check_foreign_key(t[name], t["visit_occurrence"], "visit_occurrence_id")
    return rep
