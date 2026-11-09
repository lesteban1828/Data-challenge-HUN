"""Genera los notebooks 01-07 para los datos reales (tablas resumidas de src.extract).

    python scripts/build_notebooks.py           # escribe notebooks/*.ipynb
    jupyter nbconvert --to notebook --execute --inplace notebooks/0*.ipynb
"""
from pathlib import Path

import nbformat as nbf

NB = Path(__file__).resolve().parents[1] / "notebooks"

SETUP = """\
import sys, warnings
from pathlib import Path
sys.path.insert(0, str(Path.cwd().parent))
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, matplotlib.pyplot as plt, seaborn as sns
from src import datos, flow
from src.config import FIGURES, DATA_INTERIM, DATA_PROCESSED, ETAPAS
pd.set_option("display.max_columns", 50); pd.set_option("display.float_format", "{:,.2f}".format)
sns.set_theme(style="whitegrid", context="notebook")
def guardar(nombre):
    plt.tight_layout(); plt.savefig(FIGURES / f"{nombre}.png", dpi=150, bbox_inches="tight"); plt.show()
"""


def nb(cells):
    n = nbf.v4.new_notebook()
    n.cells = [nbf.v4.new_markdown_cell(c[3:]) if c.startswith("md:") else nbf.v4.new_code_cell(c)
               for c in cells]
    n.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
    return n


NOTEBOOKS = {
"01_calidad_datos": [
"""md:# 01 · Calidad de datos
Todo el conteo se hace **en el servidor** (`python -m src.extract`); aquí solo se leen los resúmenes.
Decisiones que salen de este notebook:
1. `visit_occurrence` no sirve para medir tiempos (inicio = fin) → los tiempos salen de `visit_detail`.
2. Se reconstruyen **episodios de urgencias** (etapas de la misma persona separadas < 6 h).
3. El análisis se corta el **30-abr-2026**: desde mayo la carga está incompleta.""",
SETUP,
"""cal = pd.read_parquet(DATA_INTERIM / "calidad_intervalos.parquet")
cal["pct_duracion_cero"] = cal.duracion_cero / cal.n * 100
cal""",
"""men = pd.read_parquet(DATA_INTERIM / "mensual_tablas.parquet").dropna()
men["mes"] = pd.to_datetime(men["mes"])
men = men[(men.mes >= "2022-12-01") & (men.mes <= "2026-09-01")]
piv = men.pivot_table(index="mes", columns="tabla", values="n", aggfunc="sum")
piv = piv.rename(columns=lambda c: ETAPAS.get(int(c.split("_")[-1]), c) if c.startswith("visit_detail_") else c)
fig, ax = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
piv[[c for c in piv if c in ETAPAS.values()]].plot(ax=ax[0]); ax[0].set_title("Etapas (visit_detail) por mes")
piv[[c for c in ["condition_occurrence", "measurement"] if c in piv]].plot(ax=ax[1]); ax[1].set_title("Tablas clínicas por mes (procedure_date viene vacío)")
for a in ax: a.axvline(pd.Timestamp("2026-05-01"), color="red", ls="--", lw=1)
guardar("01_volumen_mensual")""",
"""et = datos.etapas()
ep = datos.episodios(et)
resumen = pd.Series({
    "etapas únicas (urgencias + hospitalización)": len(et),
    "episodios": len(ep), "pacientes": ep.person_id.nunique(),
    "etapas con fin nulo": int(et.fin_nulo.sum()),
    "etapas con fin < inicio (corregidas)": int(et.fin_antes_inicio.sum()),
    "episodios hospitalizados": int(ep.hospitalizado.sum()),
    "episodios con estancia atípica (excluidos de modelos)": int(ep.los_atipica.sum()),
    "episodios sin diagnóstico codificado": int(ep.dx_principal.isna().sum()),
    "procedure_date vacío en toda la tabla": "sí → procedimientos asociados por visita",
    "periodo": f"{ep.inicio.min():%Y-%m-%d} → {ep.inicio.max():%Y-%m-%d}",
})
resumen.to_frame("valor")""",
"""md:### Duración por etapa: distribución
Triage y atención de urgencias deberían durar minutos/horas; hospitalización, días. Se revisan colas extremas.""",
"""print(et.groupby("etapa")["duracion_h"].describe(percentiles=[.5,.9,.99]).round(2))
print("\\nEpisodios con estancia > 30 días:", int((ep.los_h > 720).sum()))
print("Episodios con estancia = 0:", int((ep.los_h == 0).sum()), f"({(ep.los_h == 0).mean():.1%})")""",
"""fig, ax = plt.subplots(1, 2, figsize=(13, 4))
sns.histplot(ep.loc[ep.tipo_detalle == "Urgencias con observación", "los_h"].clip(upper=72), bins=96, ax=ax[0]); ax[0].set_title("Urgencias con observación (≥15 min), horas (cortado en 72)")
sns.histplot(ep.loc[ep.hospitalizado, "los_h"].clip(upper=24*30)/24, bins=60, ax=ax[1]); ax[1].set_title("Estancia de episodios hospitalizados, días (cortado en 30)")
guardar("01_distribucion_estancia")""",
"""md:### Completitud de variables clínicas por episodio""",
"""comp = pd.Series({c: (ep[c] > 0).mean() * 100 for c in ["n_labs", "n_dx", "n_proc", "n_consultas_amb_30d"]})
comp.round(1).to_frame("% episodios con al menos 1")""",
],

"02_flujo_process_mining": [
"""md:# 02 · Flujo de pacientes (process mining)
Etapas: **Ingreso urgencias (triage)** → **Atención en urgencias** (una fila por área/traslado) → **Hospitalización**.""",
SETUP,
"""et = datos.etapas(); ep = datos.episodios(et)
st = flow.stage_stats(et); st""",
"""tr = (et.groupby(["etapa_anterior", "etapa"])["espera_previa_h"]
        .agg(n="size", espera_p50_h="median", espera_p90_h=lambda x: x.quantile(.9)).reset_index()
        .sort_values("n", ascending=False))
tr["pct"] = tr.n / tr.n.sum() * 100
tr""",
"""seq = ep["secuencia"].str.split(">").map(lambda s: " → ".join(ETAPAS[int(x)] for x in s))
# compacta repeticiones de 'Atención en urgencias' (traslados entre áreas)
import re
var = seq.map(lambda s: re.sub(r"(Atención en urgencias)( → Atención en urgencias)+", r"\\1 (×n)", s))
v = var.value_counts().rename_axis("variante").reset_index(name="n")
v["pct"] = v.n / v.n.sum() * 100; v["pct_acum"] = v.pct.cumsum()
v.head(12)""",
"""md:### ¿Dónde se va el tiempo? Composición del episodio""",
"""tipo = ep[ep.los_atipica == 0].groupby("tipo_detalle").agg(
    episodios=("episodio_id", "size"), estancia_p50_h=("los_h", "median"), estancia_p90_h=("los_h", lambda x: x.quantile(.9)),
    h_triage_p50=("h_triage", "median"), h_atencion_p50=("h_atencion_urg", "median"),
    h_hasta_hosp_p50=("h_hasta_hosp", "median"), h_hasta_hosp_p90=("h_hasta_hosp", lambda x: x.quantile(.9)),
    areas_urg_media=("n_areas_urg", "mean"))
tipo""",
"""hosp = ep[ep.tipo_episodio == "Urgencias → Hospitalización"]
fig, ax = plt.subplots(1, 2, figsize=(13, 4))
sns.histplot(hosp.h_hasta_hosp.clip(upper=96), bins=96, ax=ax[0])
ax[0].axvline(hosp.h_hasta_hosp.median(), color="red", ls="--"); ax[0].set_title("Horas desde llegada a urgencias hasta hospitalización")
hosp.groupby(hosp.inicio.dt.to_period("Q")).h_hasta_hosp.median().plot(marker="o", ax=ax[1]); ax[1].set_title("Mediana de espera para hospitalización por trimestre (h)")
guardar("02_espera_hospitalizacion")""",
"""md:### Espera entre etapas: huecos > 0 indican pacientes "en tránsito" sin etapa registrada""",
"""gap = et[et.etapa_anterior != "INICIO"].copy()
gap["tipo_gap"] = pd.cut(gap.espera_previa_h, [-1e9, -0.001, 0.001, 1, 6], labels=["superpuesta", "contigua", "<1h", "1-6h"])
pd.crosstab([gap.etapa_anterior, gap.etapa], gap.tipo_gap, normalize="index").mul(100).round(1)""",
"""md:### Mapa del proceso (pm4py, muestra de 50 000 episodios)""",
"""import pm4py
muestra = et[et.episodio_id.isin(ep.episodio_id.sample(50000, random_state=42))]
log = muestra.rename(columns={"episodio_id": "case:concept:name", "etapa": "concept:name", "inicio": "time:timestamp"})
log["case:concept:name"] = log["case:concept:name"].astype(str)
dfg, sa, ea = pm4py.discover_dfg(log[["case:concept:name", "concept:name", "time:timestamp"]])
pd.Series(dfg).sort_values(ascending=False).rename("frecuencia").to_frame()""",
"""try:
    pm4py.save_vis_dfg(dfg, sa, ea, str(FIGURES / "02_mapa_proceso.png"))
    print("Mapa guardado en reports/figures/02_mapa_proceso.png")
except Exception as e:
    print("Graphviz no disponible para dibujar el mapa:", e)""",
"""st.reset_index().to_parquet(DATA_INTERIM / "stage_stats.parquet"); tr.to_parquet(DATA_INTERIM / "transiciones.parquet"); v.to_parquet(DATA_INTERIM / "variantes.parquet")""",
],

"03_congestion_ocupacion": [
"""md:# 03 · Congestión y ocupación de urgencias""",
SETUP,
"""et = datos.etapas(); ep = datos.episodios(et)
occ = datos.censo_urgencias(et)
occ = occ[(occ.fecha_hora >= "2023-01-08") & (occ.fecha_hora < "2026-05-01")]
occ["hora"] = occ.fecha_hora.dt.hour; occ["dia"] = occ.fecha_hora.dt.dayofweek
occ.ocupacion.describe(percentiles=[.5, .9, .95, .99])""",
"""dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
fig, ax = plt.subplots(1, 2, figsize=(15, 6))
llegadas = ep.assign(hora=ep.hora_llegada, dia=ep.dia_semana).pivot_table(index="hora", columns="dia", values="episodio_id", aggfunc="count")
semanas = ep.inicio.dt.to_period("W").nunique()
sns.heatmap(llegadas / semanas, cmap="YlOrRd", ax=ax[0], xticklabels=dias, annot=False); ax[0].set_title("Llegadas promedio por hora y día")
sns.heatmap(occ.pivot_table(index="hora", columns="dia", values="ocupacion"), cmap="YlOrRd", ax=ax[1], xticklabels=dias); ax[1].set_title("Pacientes presentes en urgencias (promedio)")
guardar("03_heatmaps_llegadas_ocupacion")""",
"""diario = occ.set_index("fecha_hora").ocupacion.resample("D").max()
fig, ax = plt.subplots(figsize=(13, 4))
diario.plot(ax=ax, lw=.6, alpha=.6, label="pico diario"); diario.rolling(28).mean().plot(ax=ax, lw=2, label="media 28 días")
ax.axhline(diario.quantile(.9), color="red", ls="--", label="P90 (umbral saturación)"); ax.legend(); ax.set_title("Pico diario de ocupación en urgencias")
guardar("03_ocupacion_diaria")""",
"""md:### ¿La congestión alarga la estancia?""",
"""urg = ep[(ep.tipo_detalle == "Urgencias con observación") & (ep.los_atipica == 0)].copy()
urg["ocup_q"] = pd.qcut(urg.ocupacion_urg_llegada, 10, duplicates="drop")
efecto = urg.groupby("ocup_q", observed=True).agg(n=("los_h", "size"), estancia_p50=("los_h", "median"), estancia_media=("los_h", "mean"),
    p_reconsulta_72h=("reconsulta_72h", "mean"))
hosp = ep[ep.tipo_episodio == "Urgencias → Hospitalización"].copy()
hosp["ocup_q"] = pd.qcut(hosp.ocupacion_urg_llegada, 10, duplicates="drop")
efecto["espera_hosp_p50"] = hosp.groupby("ocup_q", observed=True).h_hasta_hosp.median().values
efecto""",
"""fig, ax = plt.subplots(figsize=(10, 4))
x = [f"{i.left:.0f}-{i.right:.0f}" for i in efecto.index]
ax.plot(x, efecto.estancia_p50, marker="o", label="Estancia en urgencias (p50, h)")
ax.plot(x, efecto.espera_hosp_p50, marker="s", label="Espera hasta hospitalización (p50, h)")
ax.set_xlabel("Pacientes en urgencias al llegar (decil)"); ax.legend(); plt.xticks(rotation=45)
guardar("03_congestion_vs_estancia")""",
"""por_franja = ep[ep.los_atipica == 0].groupby(["franja", "tipo_detalle"], observed=True).los_h.median().unstack(); por_franja""",
"""occ.to_parquet(DATA_INTERIM / "ocupacion_horaria.parquet", index=False)""",
],

"04_modelo_estancia_shap": [
"""md:# 04 · Modelo de estancia y factores de demora (LightGBM + SHAP)
- **Modelo al ingreso**: solo información disponible en las primeras 2 h → útil para priorizar.
- **Modelo explicativo**: toda la información del episodio → para entender qué alarga la estancia.
- Objetivos: *estancia prolongada* en urgencias (> P75) y *necesidad de hospitalización*.
- Validación **temporal**: entrena con el pasado, evalúa con los últimos meses.""",
SETUP + "from src import models\nfrom src.datos import FEATURES_INGRESO, FEATURES_EXPLICATIVO\nimport shap",
"""ep = datos.episodios()
ep = ep[(ep.primera_etapa != 9201) & (ep.los_atipica == 0)].copy()   # entran por urgencias, sin estancias atípicas
urg = ep[(~ep.hospitalizado) & (ep.atencion_breve == 0)].copy()   # urgencias con observación (>= 15 min)
p75 = urg.los_h.quantile(.75); urg["prolongada"] = (urg.los_h > p75).astype(int)
print(f"Episodios: {len(ep):,} · Urgencias con observación: {len(urg):,} · umbral estancia prolongada P75 = {p75:.1f} h")""",
"""md:## A. Estancia prolongada en urgencias (al ingreso)""",
"""tr, te, cut = models.temporal_split(urg, "inicio")
X = models.prepare_X(urg, FEATURES_INGRESO); y = urg.prolongada
m_prol = models.train_classifier(X.loc[tr], y.loc[tr], X.loc[te], y.loc[te])
print("corte temporal:", cut); models.eval_classification(m_prol, X.loc[te], y.loc[te])""",
"""Xr = models.prepare_X(urg, FEATURES_INGRESO)
m_reg = models.train_regressor(Xr.loc[tr], urg.log_los.loc[tr], Xr.loc[te], urg.log_los.loc[te])
models.eval_regression_log(m_reg, Xr.loc[te], urg.log_los.loc[te])""",
"""_, sv, Xs = models.shap_values(m_prol, X.loc[te], 5000)
shap.plots.beeswarm(sv[:, :, 1] if sv.values.ndim == 3 else sv, max_display=15, show=False); guardar("04_shap_prolongada_ingreso")
imp_prol = models.shap_importance_table(sv, Xs); imp_prol.head(15)""",
"""md:## B. Estancia prolongada (explicativo, con toda la información del episodio)""",
"""Xe = models.prepare_X(urg, FEATURES_EXPLICATIVO)
m_exp = models.train_classifier(Xe.loc[tr], y.loc[tr], Xe.loc[te], y.loc[te])
print(models.eval_classification(m_exp, Xe.loc[te], y.loc[te]))
_, sv_e, Xs_e = models.shap_values(m_exp, Xe.loc[te], 5000)
shap.plots.bar(sv_e[:, :, 1] if sv_e.values.ndim == 3 else sv_e, max_display=15, show=False); guardar("04_shap_prolongada_explicativo")
imp_exp = models.shap_importance_table(sv_e, Xs_e); imp_exp.head(15)""",
"""for v in ["ocupacion_urg_llegada", "n_labs", "hora_llegada", "edad"]:
    if v in Xs_e:
        vals = sv_e[:, :, 1] if sv_e.values.ndim == 3 else sv_e
        shap.plots.scatter(vals[:, v], show=False); guardar(f"04_shap_dep_{v}")""",
"""md:## C. ¿Quién terminará hospitalizado? (al ingreso)""",
"""ep["y_hosp"] = ep.hospitalizado.astype(int)
tr2, te2, _ = models.temporal_split(ep, "inicio")
Xh = models.prepare_X(ep, FEATURES_INGRESO)
m_hosp = models.train_classifier(Xh.loc[tr2], ep.y_hosp.loc[tr2], Xh.loc[te2], ep.y_hosp.loc[te2])
print(models.eval_classification(m_hosp, Xh.loc[te2], ep.y_hosp.loc[te2]))
_, sv_h, Xs_h = models.shap_values(m_hosp, Xh.loc[te2], 5000)
imp_hosp = models.shap_importance_table(sv_h, Xs_h); imp_hosp.head(10)""",
"""md:### Perfiles: diagnósticos con mayor estancia y hospitalización""",
"""dx = ep.groupby("dx_principal_nombre").agg(episodios=("episodio_id", "size"), estancia_p50_h=("los_h", "median"),
    pct_hospitalizado=("hospitalizado", "mean"), pct_reconsulta_72h=("reconsulta_72h", "mean"))
dx = dx[dx.episodios >= 500].sort_values("episodios", ascending=False); dx["pct_hospitalizado"] *= 100; dx["pct_reconsulta_72h"] *= 100
dx.head(20)""",
"""import joblib
from src.config import MODELS
joblib.dump({"prolongada": m_prol, "explicativo": m_exp, "hospitalizacion": m_hosp}, MODELS / "modelos_estancia.joblib")
pd.concat([imp_prol.assign(modelo="prolongada_ingreso"), imp_exp.assign(modelo="prolongada_explicativo"),
           imp_hosp.assign(modelo="hospitalizacion_ingreso")]).to_parquet(DATA_INTERIM / "shap_importancia.parquet", index=False)
dx.reset_index().to_parquet(DATA_INTERIM / "perfil_dx.parquet", index=False)""",
],

"05_pronostico_saturacion": [
"""md:# 05 · Pronóstico de demanda y alerta de saturación
- Llegadas **diarias** a urgencias, pronóstico **a 1 día**: ingenuo vs Holt-Winters vs LightGBM (calendario + rezagos).
- **Alerta**: día con pico de ocupación > P90 histórico.
- Validación con los últimos 120 días (abril 2026 incluido).""",
SETUP + "import lightgbm as lgb, holidays\nfrom statsmodels.tsa.holtwinters import ExponentialSmoothing\nfrom sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, roc_auc_score",
"""ep = datos.episodios()
occ = pd.read_parquet(DATA_INTERIM / "ocupacion_horaria.parquet")
d = ep[ep.primera_etapa != 9201].set_index("inicio").resample("D").size().rename("llegadas").to_frame()
d["pico_ocup"] = occ.set_index("fecha_hora").ocupacion.resample("D").max()
d = d.loc["2023-01-08":"2026-04-30"].dropna()
umbral = d.pico_ocup.quantile(.9); d["saturado"] = (d.pico_ocup > umbral).astype(int)
print(f"Umbral de saturación (P90 del pico diario): {umbral:.0f} pacientes · días saturados: {d.saturado.sum()}")
H = 120; train, test = d.iloc[:-H], d.iloc[-H:]""",
"""# Holt-Winters re-ajustado cada día (pronóstico a 1 día, como se usaría en operación)
hw_pred = []
for i in range(H):
    hist = d.llegadas.iloc[:len(d) - H + i]
    hw_pred.append(ExponentialSmoothing(hist.iloc[-365:], trend="add", damped_trend=True, seasonal="add", seasonal_periods=7).fit().forecast(1).iloc[0])
pred_hw = pd.Series(hw_pred, index=test.index)
co = holidays.Colombia(years=range(2023, 2027))
def feats(df):
    X = pd.DataFrame(index=df.index)
    X["dow"] = df.index.dayofweek; X["mes"] = df.index.month; X["dia_mes"] = df.index.day
    X["festivo"] = [x in co for x in df.index.date]; X["festivo"] = X.festivo.astype(int)
    X["post_festivo"] = X.festivo.shift(1, fill_value=0)
    X["tendencia"] = np.arange(len(df))
    for l in [1, 2, 3, 7, 14, 21, 28]: X[f"lag{l}"] = df.llegadas.shift(l)
    X["media7"] = df.llegadas.shift(1).rolling(7).mean(); X["media28"] = df.llegadas.shift(1).rolling(28).mean()
    return X
X = feats(d)
gbm = lgb.LGBMRegressor(n_estimators=600, learning_rate=0.03, num_leaves=15, verbose=-1, random_state=42)
gbm.fit(X.iloc[28:-H], d.llegadas.iloc[28:-H]); pred_gbm = gbm.predict(X.iloc[-H:])
pred_mix = (pred_gbm + pred_hw.values) / 2
naive = d.llegadas.shift(7).iloc[-H:]
met = pd.DataFrame({m: {"MAE": mean_absolute_error(test.llegadas, p), "MAPE_%": mean_absolute_percentage_error(test.llegadas, p) * 100}
                    for m, p in {"Ingenuo (misma día semana pasada)": naive, "Holt-Winters": pred_hw, "LightGBM": pred_gbm, "Promedio HW + LightGBM": pred_mix}.items()}).T
met""",
"""fig, ax = plt.subplots(figsize=(13, 4))
d.llegadas.iloc[-H-60:].plot(ax=ax, color="gray", label="real")
pd.Series(pred_hw.values, test.index).plot(ax=ax, label="Holt-Winters"); pd.Series(pred_gbm, test.index).plot(ax=ax, label="LightGBM")
ax.legend(); ax.set_title("Llegadas diarias a urgencias: pronóstico vs real (últimos 120 días)")
guardar("05_pronostico_llegadas")""",
"""md:### Alerta de saturación (clasificador del día siguiente con información disponible hoy)""",
"""Xa = X.copy(); Xa["pico_ayer"] = d.pico_ocup.shift(1); Xa["pico_media7"] = d.pico_ocup.shift(1).rolling(7).mean()
Xa["llegadas_pred"] = gbm.predict(X.fillna(X.median()))
clf = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.03, num_leaves=15, class_weight="balanced", verbose=-1, random_state=42)
clf.fit(Xa.iloc[28:-H], d.saturado.iloc[28:-H]); p = clf.predict_proba(Xa.iloc[-H:])[:, 1]
print("AUC alerta:", round(roc_auc_score(test.saturado, p), 3) if test.saturado.nunique() > 1 else "sin días saturados en test")
alerta = test.assign(prob_saturacion=p, alerta=(p >= .5).astype(int))
pd.crosstab(alerta.saturado, alerta.alerta, rownames=["real"], colnames=["alerta"])""",
"""pron = pd.DataFrame({"fecha": test.index, "llegadas_real": test.llegadas.values, "pred_holt_winters": pred_hw.values,
                     "pred_lightgbm": pred_gbm, "pico_ocupacion": test.pico_ocup.values, "prob_saturacion": p})
pron.to_parquet(DATA_INTERIM / "pronostico.parquet", index=False); met.to_parquet(DATA_INTERIM / "metricas_pronostico.parquet")""",
],

"06_simulacion_what_if": [
"""md:# 06 · Simulación what-if: espera de cama para hospitalización (SimPy)
El cuello de botella principal es la **espera en urgencias de los pacientes que se van a hospitalizar**
(mediana 16,7 h, P90 64 h). Se modela como una cola de camas:

- **Llegadas**: solicitud de cama = llegada a urgencias + tiempo clínico de urgencias (muestreado de los
  pacientes en observación que no se hospitalizan) · hospitalizaciones directas sin tiempo clínico.
- **Servicio**: estancia hospitalaria observada (empírica, último año).
- **Capacidad**: nº de camas *efectivas*, calibrado para reproducir la espera excedente observada
  (espera hasta cama − tiempo clínico). No hay dato oficial de camas: es una estimación.
- Números aleatorios comunes: base y escenarios reciben los mismos pacientes.""",
SETUP + "import simpy",
"""ep = datos.episodios()
ep = ep[(ep.los_atipica == 0) & (ep.inicio >= "2025-05-01")]          # último año
hosp = ep[ep.hospitalizado & ep.h_hospitalizacion.notna() & (ep.h_hospitalizacion > 0)].copy()
obs = ep.loc[ep.tipo_detalle == "Urgencias con observación", "los_h"].values
dias = (ep.inicio.max() - ep.inicio.min()).days
directa = (hosp.primera_etapa == 9201).values
espera_obs = hosp.loc[~directa, "h_hasta_hosp"].mean()
objetivo = max(espera_obs - obs.mean(), 0.5)
lam = len(hosp) / (dias * 24)                         # solicitudes de cama por hora
perfil = hosp.inicio.dt.hour.value_counts(normalize=True).sort_index().reindex(range(24), fill_value=0).values
los_hosp = hosp.h_hospitalizacion.values
p_directa = directa.mean()
print(f"Hospitalizaciones/día: {lam*24:.1f} · estancia hospitalaria media: {los_hosp.mean():.0f} h ({los_hosp.mean()/24:.1f} días)")
print(f"Espera media hasta cama observada: {espera_obs:.1f} h · tiempo clínico medio en urgencias: {obs.mean():.1f} h")
print(f"-> espera EXCEDENTE a reproducir: {objetivo:.1f} h · camas ocupadas promedio (Little): {lam*los_hosp.mean():.0f}")""",
"""def generar(seed, dias_sim, warmup_dias):
    # pacientes pre-generados (Poisson no homogéneo): los mismos para todos los escenarios
    rng = np.random.default_rng(seed); t, pac = 0.0, []
    rmax = lam * 24 * perfil.max()
    while t < (dias_sim + warmup_dias) * 24:
        t += rng.exponential(1 / rmax)
        u_acepta, u_extra, u_dir = rng.random(3)
        clinico = 0.0 if u_dir < p_directa else float(rng.choice(obs))
        pac.append((t, perfil[int(t) % 24] / perfil.max(), u_acepta, u_extra, clinico,
                    float(rng.choice(los_hosp)), float(rng.choice(los_hosp))))
    return pac

def simular(camas, factor_demanda=1.0, factor_los=1.0, reduccion_los_h=0.0, dias_sim=180, seed=0, warmup_dias=60):
    env = simpy.Environment(); res = simpy.Resource(env, capacity=int(camas)); esperas = []
    sol = []
    for t, p_h, u_a, u_e, clin, los, los2 in generar(seed, dias_sim, warmup_dias):
        if u_a <= p_h * min(factor_demanda, 1):
            sol.append((t + clin, los))
            if factor_demanda > 1 and u_e <= factor_demanda - 1:
                sol.append((t + clin + 0.01, los2))
    sol.sort()
    def paciente(t_sol, los):
        yield env.timeout(t_sol - env.now)
        with res.request() as r:
            yield r
            if t_sol >= warmup_dias * 24: esperas.append(env.now - t_sol)
            yield env.timeout(max(los * factor_los - reduccion_los_h, 1.0))
    for tt, ll in sol: env.process(paciente(tt, ll))
    env.run()
    return np.array(esperas)

def resumen(camas, reps=4, **kw):
    w = np.concatenate([simular(camas, seed=s, **kw) for s in range(reps)])
    return {"espera_media_h": w.mean(), "espera_p50_h": np.median(w), "espera_p90_h": np.quantile(w, .9),
            "pct_espera_mayor_12h": (w > 12).mean() * 100}

base_little = int(lam * los_hosp.mean())
calib = pd.Series({c: resumen(c, reps=2)["espera_media_h"] for c in range(base_little - 6, base_little + 40, 3)},
                  name="espera_media_sim_h")
camas = int((calib - objetivo).abs().idxmin())
print(f"Camas efectivas calibradas: {camas} (objetivo {objetivo:.1f} h)"); calib.to_frame()""",
"""escenarios = {
    "Base": dict(camas=camas),
    "+10 camas": dict(camas=camas + 10),
    "+20 camas": dict(camas=camas + 20),
    "Estancia hospitalaria -5%": dict(camas=camas, factor_los=0.95),
    "Estancia hospitalaria -10%": dict(camas=camas, factor_los=0.90),
    "Alta 4 h más temprano (gestión de egresos)": dict(camas=camas, reduccion_los_h=4),
    "+10% demanda (temporada respiratoria)": dict(camas=camas, factor_demanda=1.10),
    "+10% demanda y -10% estancia": dict(camas=camas, factor_demanda=1.10, factor_los=0.90),
}
res = pd.DataFrame({k: resumen(**v) for k, v in escenarios.items()}).T
res["cambio_espera_media_%"] = (res.espera_media_h / res.loc["Base", "espera_media_h"] - 1) * 100
res""",
"""orden = res.espera_media_h.sort_values(); b0 = res.loc["Base", "espera_media_h"]
ax = orden.plot.barh(figsize=(10, 5), color=["#2a9d8f" if v < b0 - 1e-9 else ("#e76f51" if v > b0 + 1e-9 else "#8d99ae") for v in orden])
ax.set_xlabel("Espera media simulada por cama (h, excedente sobre el tiempo clínico)"); ax.set_title("Escenarios what-if: espera de cama desde urgencias")
guardar("06_escenarios")
res.rename_axis("escenario").reset_index().to_parquet(DATA_INTERIM / "escenarios.parquet", index=False)""",
],

"07_export_powerbi": [
"""md:# 07 · Exportar modelo estrella para Power BI
Se escribe en `DATA_PROCESSED` (disco D:). Tablas: `fact_episodio`, `fact_etapa`, `fact_ocupacion_horaria`,
`dim_fecha`, `dim_diagnostico`, `pronostico`, `escenarios`, `shap_importancia`, `perfil_dx`.""",
SETUP,
"""et = datos.etapas(); ep = datos.episodios(et)
cols = ["episodio_id", "person_id", "inicio", "fin", "los_h", "tipo_episodio", "tipo_detalle", "los_atipica", "hospitalizado", "paso_triage", "h_triage",
        "h_atencion_urg", "h_hospitalizacion", "h_hasta_hosp", "h_hasta_primer_lab", "n_areas_urg", "n_labs", "n_dx", "n_proc",
        "edad", "grupo_edad", "sexo", "hora_llegada", "dia_semana", "franja", "festivo", "episodios_previos",
        "reconsulta_72h", "ocupacion_urg_llegada", "dx_principal"]
f_ep = ep[cols].assign(fecha=ep.inicio.dt.date)
f_et = et[["episodio_id", "orden", "etapa", "inicio", "fin", "duracion_h", "espera_previa_h", "etapa_anterior"]]
dim_fecha = pd.DataFrame({"fecha": pd.date_range("2023-01-01", "2026-04-30")})
dim_fecha = dim_fecha.assign(anio=dim_fecha.fecha.dt.year, mes=dim_fecha.fecha.dt.month, nombre_mes=dim_fecha.fecha.dt.strftime("%b"),
    dia_semana=dim_fecha.fecha.dt.dayofweek, trimestre=dim_fecha.fecha.dt.quarter)
dim_dx = ep.groupby(["dx_principal", "dx_principal_nombre"]).size().rename("episodios").reset_index()
salidas = {"fact_episodio": f_ep, "fact_etapa": f_et, "dim_fecha": dim_fecha, "dim_diagnostico": dim_dx,
           "fact_ocupacion_horaria": pd.read_parquet(DATA_INTERIM / "ocupacion_horaria.parquet")}
for n in ["pronostico", "escenarios", "shap_importancia", "perfil_dx", "variantes", "transiciones"]:
    p = DATA_INTERIM / f"{n}.parquet"
    if p.exists(): salidas[n] = pd.read_parquet(p)
for n, df in salidas.items():
    df.to_csv(DATA_PROCESSED / f"{n}.csv", index=False, encoding="utf-8-sig")
    print(f"✔ {n:<24} {len(df):>10,} filas")""",
],
}

if __name__ == "__main__":
    for name, cells in NOTEBOOKS.items():
        nbf.write(nb(cells), NB / f"{name}.ipynb")
        print("✔", name)
