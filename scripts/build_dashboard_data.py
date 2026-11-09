"""Genera dashboard/data.js con datos AGREGADOS (sin nada a nivel de paciente) para el dashboard web.

    python scripts/build_dashboard_data.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import datos  # noqa: E402
from src.config import DATA_INTERIM  # noqa: E402

OUT = ROOT / "dashboard" / "data.js"


def r(x, n=1):
    return None if pd.isna(x) else round(float(x), n)


def main():
    et = datos.etapas()
    ep = datos.episodios(et)
    ok = ep[ep.los_atipica == 0]
    hosp = ok[ok.tipo_detalle == "Urgencias → Hospitalización"]
    obs = ok[ok.tipo_detalle == "Urgencias con observación"]
    dias = (ep.inicio.max().normalize() - ep.inicio.min().normalize()).days + 1

    kpi = {
        "episodios": int(len(ep)), "pacientes": int(ep.person_id.nunique()),
        "episodios_dia": r(len(ep) / dias), "pct_hosp": r(ok.hospitalizado.mean() * 100),
        "cama_p50": r(hosp.h_hasta_hosp.median()), "cama_p90": r(hosp.h_hasta_hosp.quantile(.9)),
        "obs_p50": r(obs.los_h.median()), "obs_p90": r(obs.los_h.quantile(.9)),
        "pct_breve": r(ok.atencion_breve.mean() * 100), "reconsulta_72h": r(ok.reconsulta_72h.mean() * 100),
        "desde": f"{ep.inicio.min():%Y-%m-%d}", "hasta": f"{ep.inicio.max():%Y-%m-%d}",
    }

    m = ok.set_index("inicio")
    mensual = pd.DataFrame({
        "episodios": m.resample("MS").size(),
        "cama_p50": hosp.set_index("inicio").h_hasta_hosp.resample("MS").median(),
        "obs_p50": obs.set_index("inicio").los_h.resample("MS").median(),
        "hosp": m.hospitalizado.resample("MS").sum(),
    })
    mensual = [{"mes": f"{i:%Y-%m}", **{k: r(v) for k, v in row.items()}} for i, row in mensual.iterrows()]

    tipos = (ok.groupby("tipo_detalle").agg(n=("episodio_id", "size"), p50=("los_h", "median"),
                                            p90=("los_h", lambda x: x.quantile(.9))).reset_index())
    tipos = [{"tipo": t.tipo_detalle, "n": int(t.n), "p50": r(t.p50), "p90": r(t.p90)} for t in tipos.itertuples()]

    semanas = ep.inicio.dt.to_period("W").nunique()
    lleg = ep.groupby([ep.dia_semana, ep.hora_llegada]).size() / semanas
    occ = pd.read_parquet(DATA_INTERIM / "ocupacion_horaria.parquet")
    oc = occ.groupby(["dia", "hora"]).ocupacion.mean()
    heat = {"llegadas": [[r(lleg.get((d, h), 0)) for h in range(24)] for d in range(7)],
            "ocupacion": [[r(oc.get((d, h), np.nan), 0) for h in range(24)] for d in range(7)]}

    diario = occ.set_index("fecha_hora").ocupacion.resample("D").max()
    umbral = float(diario.quantile(.9))
    ocup_diaria = [{"f": f"{i:%Y-%m-%d}", "v": int(v)} for i, v in diario.items()]

    def deciles(df, col):
        q = pd.qcut(df.ocupacion_urg_llegada, 10, labels=False, duplicates="drop")
        return [r(v, 2) for v in df.groupby(q)[col].median().values]
    # misma población que el notebook 03 (todos los episodios urgencias → hospitalización)
    hosp_all = ep[ep.tipo_detalle == "Urgencias → Hospitalización"]
    congestion = {"cama": deciles(hosp_all, "h_hasta_hosp"), "obs": deciles(obs, "los_h")}

    dist_cama = np.histogram(hosp.h_hasta_hosp.clip(upper=96), bins=24, range=(0, 96))[0].tolist()

    tr = pd.read_parquet(DATA_INTERIM / "transiciones.parquet")
    trans = [{"de": t.etapa_anterior, "a": t.etapa, "n": int(t.n)} for t in tr.itertuples()]
    var = pd.read_parquet(DATA_INTERIM / "variantes.parquet").head(8)
    variantes = [{"v": v.variante, "n": int(v.n), "pct": r(v.pct)} for v in var.itertuples()]

    shap = pd.read_parquet(DATA_INTERIM / "shap_importancia.parquet")
    shap_d = {mod: [{"var": s.variable, "imp": r(s.importancia_shap, 3)} for s in g.head(10).itertuples()]
              for mod, g in shap.groupby("modelo")}
    dx = pd.read_parquet(DATA_INTERIM / "perfil_dx.parquet")
    dx = dx[dx.dx_principal_nombre != "Sin diagnóstico codificado"].head(12)
    perfil_dx = [{"dx": d.dx_principal_nombre, "n": int(d.episodios), "p50": r(d.estancia_p50_h),
                  "hosp": r(d.pct_hospitalizado)} for d in dx.itertuples()]

    edad = ok.groupby("grupo_edad", observed=True).agg(n=("episodio_id", "size"), hosp=("hospitalizado", "mean"))
    edad = [{"g": str(i), "n": int(e.n), "hosp": r(e.hosp * 100)} for i, e in edad.iterrows()]

    pr = pd.read_parquet(DATA_INTERIM / "pronostico.parquet")
    pron = [{"f": f"{p.fecha:%Y-%m-%d}", "real": int(p.llegadas_real), "hw": r(p.pred_holt_winters),
             "gbm": r(p.pred_lightgbm), "prob": r(p.prob_saturacion, 3)} for p in pr.itertuples()]
    met = pd.read_parquet(DATA_INTERIM / "metricas_pronostico.parquet")
    metricas = [{"modelo": i, "mae": r(x.MAE), "mape": r(x["MAPE_%"])} for i, x in met.iterrows()]

    esc = pd.read_parquet(DATA_INTERIM / "escenarios.parquet")
    escenarios = [{"e": e.escenario, "media": r(e.espera_media_h, 2), "p90": r(e.espera_p90_h),
                   "pct12": r(e.pct_espera_mayor_12h)} for e in esc.itertuples()]

    data = dict(kpi=kpi, mensual=mensual, tipos=tipos, heat=heat, ocup_diaria=ocup_diaria, umbral=round(umbral),
                congestion=congestion, dist_cama=dist_cama, trans=trans, variantes=variantes, shap=shap_d,
                perfil_dx=perfil_dx, edad=edad, pron=pron, metricas=metricas, escenarios=escenarios)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("window.HUN = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")
    print(f"✔ {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
