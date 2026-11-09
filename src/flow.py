"""Reconstrucción del flujo hospitalario: event log, transiciones, variantes y ocupación."""
import numpy as np
import pandas as pd

S, E = "visit_detail_start_datetime", "visit_detail_end_datetime"


def build_event_log(visit_detail: pd.DataFrame, concept_names: dict | None = None) -> pd.DataFrame:
    """Una fila por etapa, ordenada dentro de cada visita, con duración y espera previa (horas).

    espera_previa_h = inicio de esta etapa − fin de la etapa anterior.
    Valores negativos indican etapas superpuestas.
    """
    ev = visit_detail.dropna(subset=[S]).sort_values(["visit_occurrence_id", S, E]).copy()
    ev["etapa"] = ev["visit_detail_concept_id"]
    if concept_names:
        ev["etapa"] = ev["etapa"].map(concept_names).fillna(ev["etapa"].astype(str))
    ev["etapa"] = ev["etapa"].astype(str)

    g = ev.groupby("visit_occurrence_id")
    ev["orden"] = g.cumcount() + 1
    ev["duracion_h"] = (ev[E] - ev[S]).dt.total_seconds() / 3600
    ev["espera_previa_h"] = (ev[S] - g[E].shift()).dt.total_seconds() / 3600
    ev["etapa_anterior"] = g["etapa"].shift().fillna("INICIO")
    ev["etapa_siguiente"] = g["etapa"].shift(-1).fillna("FIN")
    return ev


def transitions(ev: pd.DataFrame) -> pd.DataFrame:
    """Matriz de transiciones etapa_anterior → etapa con volumen y estadísticos de espera."""
    t = (ev.groupby(["etapa_anterior", "etapa"])["espera_previa_h"]
           .agg(n="size", espera_media_h="mean", espera_p50_h="median",
                espera_p90_h=lambda x: x.quantile(0.9))
           .reset_index()
           .sort_values("n", ascending=False))
    t["pct_casos"] = (t["n"] / t["n"].sum() * 100).round(2)
    return t


def stage_stats(ev: pd.DataFrame) -> pd.DataFrame:
    """Duración por etapa: volumen, media, mediana, P90."""
    return (ev.groupby("etapa")["duracion_h"]
              .agg(n="size", media_h="mean", p50_h="median",
                   p90_h=lambda x: x.quantile(0.9))
              .sort_values("p50_h", ascending=False))


def variants(ev: pd.DataFrame, top: int = 20) -> pd.DataFrame:
    """Trayectorias (secuencia de etapas) más frecuentes y su cobertura acumulada."""
    trace = ev.groupby("visit_occurrence_id")["etapa"].agg(" → ".join)
    v = trace.value_counts().rename_axis("variante").reset_index(name="n")
    v["pct"] = v["n"] / v["n"].sum() * 100
    v["pct_acum"] = v["pct"].cumsum()
    return v.head(top)


def to_pm4py(ev: pd.DataFrame) -> pd.DataFrame:
    """Formato estándar de pm4py (case:concept:name, concept:name, time:timestamp)."""
    return ev.rename(columns={
        "visit_occurrence_id": "case:concept:name",
        "etapa": "concept:name",
        S: "time:timestamp",
    })[["case:concept:name", "concept:name", "time:timestamp"]].assign(
        **{"case:concept:name": lambda d: d["case:concept:name"].astype(str)})


def census(df: pd.DataFrame, start: str, end: str, freq: str = "h",
           group: str | None = None) -> pd.DataFrame:
    """Ocupación (pacientes presentes) en cada periodo con el método +1/−1.

    Visitas sin fin se consideran abiertas hasta la última fecha observada.
    """
    d = df.dropna(subset=[start]).copy()
    d[end] = d[end].fillna(d[start].max())
    groups = [(None, d)] if group is None else d.groupby(group)
    out = []
    for key, sub in groups:
        ev = pd.concat([
            pd.Series(1, index=sub[start].dt.floor(freq)),
            pd.Series(-1, index=sub[end].dt.floor(freq)),
        ])
        occ = ev.groupby(level=0).sum().sort_index().cumsum()
        idx = pd.date_range(occ.index.min(), occ.index.max(), freq=freq)
        occ = occ.reindex(idx).ffill().fillna(0).rename("ocupacion").to_frame()
        if group is not None:
            occ[group] = key
        out.append(occ)
    return pd.concat(out).rename_axis("fecha_hora").reset_index()


def arrivals(df: pd.DataFrame, start: str, freq: str = "h", group: str | None = None) -> pd.DataFrame:
    """Número de llegadas por periodo."""
    keys = [pd.Grouper(key=start, freq=freq)] + ([group] if group else [])
    return (df.groupby(keys).size().rename("llegadas")
              .reset_index().rename(columns={start: "fecha_hora"}))


def occupancy_at_arrival(visits: pd.DataFrame, occ: pd.DataFrame,
                         start: str = "visit_start_datetime") -> pd.Series:
    """Ocupación total en la hora de llegada de cada visita (variable de 'cola')."""
    m = occ.set_index("fecha_hora")["ocupacion"]
    return visits[start].dt.floor("h").map(m).astype(float)


def hour_weekday_matrix(df: pd.DataFrame, col: str, value: str | None = None,
                        agg: str = "count") -> pd.DataFrame:
    """Matriz hora (filas) × día de la semana (columnas) para heatmaps."""
    d = df.assign(hora=df[col].dt.hour, dia=df[col].dt.dayofweek)
    if value is None:
        m = d.pivot_table(index="hora", columns="dia", values=col, aggfunc="count")
    else:
        m = d.pivot_table(index="hora", columns="dia", values=value, aggfunc=agg)
    m.columns = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"][: len(m.columns)]
    return m
