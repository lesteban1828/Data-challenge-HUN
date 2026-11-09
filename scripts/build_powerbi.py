"""Genera el proyecto Power BI (PBIP: modelo TMDL + reporte PBIR), el tema glass y las tablas.

    python scripts/build_powerbi.py

Salidas:
  D:/HUN_DataChallenge_datos/powerbi/*.csv     tablas limpias para el modelo (fuera del repo)
  powerbi/HUN_Flujo.pbip (+ carpetas)          abrir con Power BI Desktop
  powerbi/tema_HUN_clinico.json                  tema (Vista → Temas → Buscar temas)
"""
import base64
import io
import json
import shutil
import sys
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.config import DATA_DIR, DATA_INTERIM, DATA_PROCESSED  # noqa: E402

PBI_DATA = DATA_DIR / "powerbi"
PBI_DIR = ROOT / "powerbi"
NAME = "HUN_Flujo"
DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


# ----------------------------------------------------------------------------- datos
def preparar_datos() -> dict[str, pd.DataFrame]:
    PBI_DATA.mkdir(parents=True, exist_ok=True)
    ep = pd.read_csv(DATA_PROCESSED / "fact_episodio.csv", encoding="utf-8-sig")
    for c in ["hospitalizado", "paso_triage"]:
        ep[c] = ep[c].map({True: 1, False: 0, "True": 1, "False": 0}).fillna(0).astype(int)
    ep["inicio"] = pd.to_datetime(ep["inicio"])
    ep["fecha"] = ep["inicio"].dt.strftime("%Y-%m-%d")
    ep["inicio"] = ep["inicio"].dt.strftime("%Y-%m-%d %H:%M:%S")
    ep["dia_nombre"] = ep["dia_semana"].map(lambda d: DIAS[int(d)])
    ep["rango_espera_cama"] = pd.cut(ep["h_hasta_hosp"], list(range(0, 100, 4)) + [1e9], right=False,
                                     labels=[f"{i:02d}-{i+4:02d} h" for i in range(0, 96, 4)] + ["96+ h"]).astype(str)
    ep.loc[ep["h_hasta_hosp"].isna(), "rango_espera_cama"] = ""
    dims = pd.read_csv(DATA_PROCESSED / "dim_diagnostico.csv", encoding="utf-8-sig")
    ep = ep.merge(dims[["dx_principal", "dx_principal_nombre"]], on="dx_principal", how="left")
    ep["dx_principal_nombre"] = ep["dx_principal_nombre"].fillna("Sin diagnóstico codificado")
    cols = ["episodio_id", "fecha", "inicio", "los_h", "tipo_episodio", "tipo_detalle", "los_atipica", "hospitalizado",
            "h_triage", "h_atencion_urg", "h_hospitalizacion", "h_hasta_hosp", "rango_espera_cama", "n_areas_urg",
            "n_labs", "n_dx", "n_proc", "edad", "grupo_edad", "sexo", "hora_llegada", "dia_semana", "dia_nombre",
            "franja", "festivo", "episodios_previos", "reconsulta_72h", "ocupacion_urg_llegada", "dx_principal_nombre"]
    ep = ep[cols]
    orden_edad = {"0-4": 1, "5-17": 2, "18-29": 3, "30-44": 4, "45-59": 5, "60-74": 6, "75+": 7}
    ep["orden_edad"] = ep["grupo_edad"].map(orden_edad).fillna(8).astype(int)

    f = pd.DataFrame({"fecha": pd.date_range("2023-01-01", "2026-04-30")})
    fecha = pd.DataFrame({"fecha": f.fecha.dt.strftime("%Y-%m-%d"), "anio": f.fecha.dt.year,
                          "mes": f.fecha.dt.month, "anio_mes": f.fecha.dt.strftime("%Y-%m"),
                          "nombre_mes": f.fecha.dt.month.map(lambda m: MESES[m - 1]),
                          "trimestre": "T" + f.fecha.dt.quarter.astype(str),
                          "dia_semana": f.fecha.dt.dayofweek, "dia_nombre": f.fecha.dt.dayofweek.map(lambda d: DIAS[d])})

    occ = pd.read_parquet(DATA_INTERIM / "ocupacion_horaria.parquet")
    dia = occ.set_index("fecha_hora").ocupacion.resample("D").max().rename("pico").reset_index()
    umbral = float(dia.pico.quantile(.9))
    dia["media_28d"] = dia.pico.rolling(28).mean().round(1)
    dia["umbral_p90"] = round(umbral)
    dia["fecha"] = dia.fecha_hora.dt.strftime("%Y-%m-%d")
    ocup_dia = dia[["fecha", "pico", "media_28d", "umbral_p90"]]
    ocup_hora = occ.groupby(["dia", "hora"]).ocupacion.mean().round(1).reset_index()
    ocup_hora["dia_nombre"] = ocup_hora["dia"].map(lambda d: DIAS[int(d)])
    ocup_hora["hora_txt"] = ocup_hora["hora"].map(lambda h: f"{int(h):02d}")

    # congestión vs espera (misma definición que el notebook 03)
    from src import datos
    e = datos.episodios()
    hosp = e[e.tipo_detalle == "Urgencias → Hospitalización"]
    obs = e[(e.tipo_detalle == "Urgencias con observación") & (e.los_atipica == 0)]
    dec = lambda df, col: df.groupby(pd.qcut(df.ocupacion_urg_llegada, 10, labels=False, duplicates="drop"))[col].median()
    cong = pd.DataFrame({"decil": range(1, 11), "espera_cama_h": dec(hosp, "h_hasta_hosp").round(2).values,
                         "estancia_observacion_h": dec(obs, "los_h").round(2).values})

    pron = pd.read_csv(DATA_PROCESSED / "pronostico.csv", encoding="utf-8-sig")
    pron["prob_saturacion"] = (pron["prob_saturacion"] * 100).round(2)
    met = pd.read_parquet(DATA_INTERIM / "metricas_pronostico.parquet").rename_axis("modelo").reset_index()
    met.columns = ["modelo", "mae", "mape"]
    esc = pd.read_csv(DATA_PROCESSED / "escenarios.csv", encoding="utf-8-sig")
    esc.columns = ["escenario", "espera_media_h", "espera_p50_h", "espera_p90_h", "pct_espera_mas_12h", "cambio_pct"]
    esc["orden"] = esc["espera_media_h"].rank(ascending=False).astype(int)
    tope = 16.0   # la barra de +10 % de demanda (269 h) se recorta para que se vean las demás
    esc["espera_grafico_h"] = esc["espera_media_h"].clip(upper=tope).round(2)
    esc["escenario"] = esc.apply(lambda r: f"{r.escenario} ({r.espera_media_h:.0f} h, colapsa)"
                                 if r.espera_media_h > tope else ("Situación actual (base)" if r.escenario == "Base" else r.escenario), axis=1)
    shap = pd.read_csv(DATA_PROCESSED / "shap_importancia.csv", encoding="utf-8-sig")
    nombres = {"prolongada_explicativo": "Estancia prolongada (todo el episodio)",
               "hospitalizacion_ingreso": "Hospitalización (al ingreso)",
               "prolongada_ingreso": "Estancia prolongada (al ingreso)"}
    shap["modelo"] = shap["modelo"].map(nombres)
    VAR = {"n_areas_urg": "Áreas de urgencias recorridas", "n_labs": "N.º de laboratorios", "n_proc": "N.º de procedimientos",
           "n_dx_2h": "Diagnósticos en 2 h", "hora_llegada": "Hora de llegada", "primera_etapa_nombre": "Área de entrada",
           "mes": "Mes", "dx_principal_nombre": "Diagnóstico principal", "h_desde_episodio_previo": "Tiempo desde el último episodio",
           "edad": "Edad", "n_tipos_lab": "Tipos de laboratorio", "llegadas_ult_6h": "Llegadas últimas 6 h",
           "ocupacion_urg_llegada": "Ocupación al llegar", "n_labs_2h": "Laboratorios en 2 h", "n_dx": "N.º de diagnósticos",
           "n_consultas_amb_30d": "Consultas ambulatorias 30 d", "sexo": "Sexo", "dia_semana": "Día de la semana",
           "episodios_previos": "Episodios previos", "festivo": "Festivo", "fin_de_semana": "Fin de semana",
           "reconsulta_previa_30d": "Reconsulta previa 30 d"}
    shap["variable"] = shap["variable"].map(VAR).fillna(shap["variable"])
    shap_est = shap[shap.modelo == nombres["prolongada_explicativo"]].nlargest(10, "importancia_shap")[["variable", "importancia_shap"]]
    shap_hosp = shap[shap.modelo == nombres["hospitalizacion_ingreso"]].nlargest(10, "importancia_shap")[["variable", "importancia_shap"]]
    perfil = pd.read_csv(DATA_PROCESSED / "perfil_dx.csv", encoding="utf-8-sig")
    perfil = perfil[(perfil.dx_principal_nombre != "Sin diagnóstico codificado") & (perfil.episodios >= 1000)]
    trans = pd.read_csv(DATA_PROCESSED / "transiciones.csv", encoding="utf-8-sig")
    var = pd.read_csv(DATA_PROCESSED / "variantes.csv", encoding="utf-8-sig").head(15)
    recs = pd.DataFrame({"prioridad": range(1, 8), "recomendacion": [
        "Gestión de egresos: alta antes del mediodía y sala de egreso",
        "Reducir la estancia hospitalaria 5-10 % con rutas clínicas",
        "Alerta temprana de hospitalización desde el triage",
        "Menos traslados entre áreas de urgencias",
        "Tablero diario de saturación con pronóstico a 1 día",
        "Rutas rápidas para los 5 diagnósticos con estancias más largas",
        "Plan de contingencia para temporadas de alta demanda"], "impacto": [
        "Espera de cama simulada de 13,9 a 3,0 h", "Espera de cama < 1 h en la simulación",
        "Preparar la cama horas antes (AUC 0,77)", "Menos estancias > 13,8 h en urgencias",
        "Reforzar antes del pico (MAPE 13,6 %)", "Estancias de 8-11,5 h en observación",
        "Con +10 % de demanda sin medidas la cola colapsa"]})

    tablas = {"Episodios": ep, "Fecha": fecha, "OcupacionDiaria": ocup_dia, "OcupacionHora": ocup_hora,
              "Congestion": cong, "Pronostico": pron, "MetricasPronostico": met, "Escenarios": esc,
              "SHAP": shap, "ShapEstancia": shap_est, "ShapHospitalizacion": shap_hosp, "PerfilDx": perfil, "Transiciones": trans, "Variantes": var, "Recomendaciones": recs}
    for n, df in tablas.items():
        df.to_csv(PBI_DATA / f"{n}.csv", index=False, encoding="utf-8")
        print(f"  ✔ {n:<20} {len(df):>9,} filas")
    return tablas


# ----------------------------------------------------------------------------- tema
NAVY, TEAL, AMBER, RED, INK, MUTED, LINE, PAGE = "#14324F", "#2A9D8F", "#E9A23B", "#D1495B", "#1E2A36", "#5E6B78", "#D9E0E7", "#EEF2F5"


def fondo_png() -> bytes:
    """Fondo claro con franja superior azul marino (zona del título de cada página)."""
    from PIL import Image, ImageDraw
    w, h = 1280, 720
    im = Image.new("RGB", (w, h), PAGE)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w, 84], fill=NAVY)
    d.rectangle([0, 84, w, 88], fill=TEAL)
    buf = io.BytesIO(); im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def tema() -> dict:
    sol = lambda c: {"solid": {"color": c}}
    return {
        "name": "HUN Clínico",
        "dataColors": [NAVY, TEAL, "#8FA3B6", AMBER, "#4F7CAC", "#A7C4BC", "#C9B79C", RED],
        "good": TEAL, "neutral": AMBER, "bad": RED, "maximum": NAVY, "center": "#9DB4C8", "minimum": "#EAF0F5",
        "foreground": INK, "foregroundNeutralSecondary": MUTED, "foregroundNeutralTertiary": "#8D99A6",
        "background": "#FFFFFF", "backgroundLight": "#F6F8FA", "backgroundNeutral": LINE, "tableAccent": NAVY,
        "textClasses": {
            "callout": {"fontSize": 24, "fontFace": "Segoe UI Semibold", "color": NAVY},
            "title": {"fontSize": 11, "fontFace": "Segoe UI Semibold", "color": INK},
            "header": {"fontSize": 10, "fontFace": "Segoe UI Semibold", "color": INK},
            "label": {"fontSize": 9, "fontFace": "Segoe UI", "color": MUTED},
        },
        "visualStyles": {
            "*": {"*": {
                "background": [{"show": True, "color": sol("#FFFFFF"), "transparency": 0}],
                "border": [{"show": True, "color": sol(LINE), "radius": 6}],
                "dropShadow": [{"show": False}],
                "visualHeader": [{"show": True, "transparency": 100}],
                "title": [{"show": True, "fontColor": sol(INK), "fontSize": 11}],
                "padding": [{"top": 10, "bottom": 10, "left": 12, "right": 12}],
                "categoryAxis": [{"labelColor": sol(MUTED), "gridlineShow": False}],
                "valueAxis": [{"labelColor": sol(MUTED), "gridlineColor": sol("#E6EBF0"), "gridlineStyle": "dotted"}],
                "legend": [{"labelColor": sol(MUTED)}],
                "labels": [{"color": sol(INK)}],
            }},
            "page": {"*": {
                "background": [{"image": {"name": "fondo_clinico", "scaling": "Fill",
                                          "url": "data:image/png;base64," + base64.b64encode(fondo_png()).decode()},
                                "transparency": 0}],
                "outspace": [{"color": sol("#DDE4EA"), "transparency": 0}],
            }},
            "card": {"*": {"labels": [{"color": sol(NAVY), "fontSize": 24}],
                           "categoryLabels": [{"color": sol(MUTED), "fontSize": 9}],
                           "border": [{"show": True, "color": sol(LINE), "radius": 6}]}},
            "tableEx": {"*": {"grid": [{"gridHorizontalColor": sol(LINE), "gridVertical": False}],
                              "columnHeaders": [{"fontColor": sol("#FFFFFF"), "backColor": sol(NAVY)}],
                              "values": [{"fontColorPrimary": sol(INK), "backColorPrimary": sol("#FFFFFF"),
                                          "fontColorSecondary": sol(INK), "backColorSecondary": sol("#F4F7FA")}]}},
            "slicer": {"*": {"items": [{"fontColor": sol(INK)}], "header": [{"fontColor": sol(INK)}]}},
        },
    }


# ----------------------------------------------------------------------------- modelo (TMDL)
TIPOS = {"int64": ("int64", "Int64.Type"), "float64": ("double", "type number"), "object": ("string", "type text")}
FECHAS = {("Episodios", "fecha"): "date", ("Episodios", "inicio"): "dateTime", ("Fecha", "fecha"): "date",
          ("OcupacionDiaria", "fecha"): "date", ("Pronostico", "fecha"): "date"}
SORT_BY = {("Episodios", "dia_nombre"): "dia_semana", ("Fecha", "dia_nombre"): "dia_semana",
           ("Fecha", "nombre_mes"): "mes", ("OcupacionHora", "dia_nombre"): "dia",
           ("Escenarios", "escenario"): "orden", ("Episodios", "grupo_edad"): "orden_edad"}

MEDIDAS = [
    ("Episodios", "COUNTROWS ( Episodios )", "#,0"),
    ("Episodios por día", "DIVIDE ( [Episodios], DISTINCTCOUNT ( Episodios[fecha] ) )", "#,0"),
    ("Episodios válidos", "CALCULATE ( [Episodios], Episodios[los_atipica] = 0 )", "#,0"),
    ("% hospitalizados", "DIVIDE ( CALCULATE ( [Episodios válidos], Episodios[hospitalizado] = 1 ), [Episodios válidos] )", "0.0%"),
    ("Espera de cama mediana (h)", "CALCULATE ( MEDIAN ( Episodios[h_hasta_hosp] ), Episodios[tipo_detalle] = \"Urgencias → Hospitalización\" )", "0.0"),
    ("Espera de cama P90 (h)", "CALCULATE ( PERCENTILEX.INC ( FILTER ( Episodios, NOT ISBLANK ( Episodios[h_hasta_hosp] ) ), Episodios[h_hasta_hosp], 0.9 ), Episodios[tipo_detalle] = \"Urgencias → Hospitalización\" )", "0.0"),
    ("Observación mediana (h)", "CALCULATE ( MEDIAN ( Episodios[los_h] ), Episodios[tipo_detalle] = \"Urgencias con observación\", Episodios[los_atipica] = 0 )", "0.0"),
    ("Estancia mediana (h)", "CALCULATE ( MEDIAN ( Episodios[los_h] ), Episodios[los_atipica] = 0 )", "0.0"),
    ("Estancia P90 (h)", "CALCULATE ( PERCENTILEX.INC ( Episodios, Episodios[los_h], 0.9 ), Episodios[los_atipica] = 0 )", "0.0"),
    ("% atenciones breves", "DIVIDE ( CALCULATE ( [Episodios válidos], Episodios[tipo_detalle] = \"Urgencias breve (<15 min)\" ), [Episodios válidos] )", "0%"),
    ("% reconsulta 72 h", "CALCULATE ( AVERAGE ( Episodios[reconsulta_72h] ), Episodios[los_atipica] = 0 )", "0.0%"),
    ("Hospitalizados desde urgencias", "CALCULATE ( [Episodios], Episodios[tipo_detalle] = \"Urgencias → Hospitalización\" )", "#,0"),
    ("Pacientes en urgencias (promedio)", "AVERAGE ( OcupacionHora[ocupacion] )", "#,0"),
    ("Pico de ocupación", "MAX ( OcupacionDiaria[pico] )", "#,0"),
    ("Riesgo de saturación", "VAR p = MAX ( Pronostico[prob_saturacion] ) RETURN SWITCH ( TRUE (), p >= 50, \"Alto\", p >= 30, \"Medio\", \"Bajo\" )", None),
]


def tmdl_tabla(nombre: str, df: pd.DataFrame) -> str:
    L = [f"table {nombre}", f"\tlineageTag: {uuid.uuid4()}", ""]
    if nombre == "Episodios":
        for m, expr, fmt in MEDIDAS:
            L += [f"\tmeasure '{m}' = {expr}"]
            if fmt:
                L += [f"\t\tformatString: {fmt}"]
            L += [f"\t\tlineageTag: {uuid.uuid4()}", ""]
    tipos_m = []
    for c in df.columns:
        dt = FECHAS.get((nombre, c))
        fmt_fecha = None
        if dt:
            m = "type date" if dt == "date" else "type datetime"
            fmt_fecha = "yyyy-mm-dd" if dt == "date" else "yyyy-mm-dd hh:nn"
            dt = "dateTime"          # TMDL solo admite dateTime
        else:
            dt, m = TIPOS.get(str(df[c].dtype), ("string", "type text"))
        tipos_m.append(f'{{"{c}", {m}}}')
        resumen = "sum" if dt in ("int64", "double") and not c.endswith("_id") and c not in (
            "anio", "mes", "dia_semana", "dia", "hora", "hora_llegada", "decil", "prioridad", "orden", "festivo", "orden_edad") else "none"
        L += [f"\tcolumn {c}", f"\t\tdataType: {dt}", f"\t\tsummarizeBy: {resumen}", f"\t\tsourceColumn: {c}",
              f"\t\tlineageTag: {uuid.uuid4()}"]
        if (nombre, c) in SORT_BY:
            L += [f"\t\tsortByColumn: {SORT_BY[(nombre, c)]}"]
        if dt == "double":
            L += ["\t\tformatString: 0.0"]
        if fmt_fecha:
            L += [f"\t\tformatString: {fmt_fecha}"]
        L += [""]
    m_tipos = ", ".join(tipos_m)
    L += [f"\tpartition {nombre} = m", "\t\tmode: import", "\t\tsource =", "\t\t\t\tlet",
          f'\t\t\t\t    Origen = Csv.Document(File.Contents(Ruta & "{nombre}.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),',
          "\t\t\t\t    Encabezados = Table.PromoteHeaders(Origen, [PromoteAllScalars = true]),",
          f'\t\t\t\t    Tipos = Table.TransformColumnTypes(Encabezados, {{{m_tipos}}}, "en-US")',
          "\t\t\t\tin", "\t\t\t\t    Tipos", ""]
    return "\n".join(L) + "\n"


def escribir_modelo(tablas: dict) -> None:
    sm = PBI_DIR / f"{NAME}.SemanticModel"
    d = sm / "definition"
    (d / "tables").mkdir(parents=True, exist_ok=True)
    (sm / "definition.pbism").write_text(json.dumps({"version": "4.2", "settings": {}}, indent=2), encoding="utf-8")
    (d / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1600\n", encoding="utf-8")
    refs = "\n".join(f"ref table {n}" for n in tablas)
    (d / "model.tmdl").write_text(
        "model Model\n\tculture: es-CO\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tsourceQueryCulture: es-CO\n"
        "\tdataAccessOptions\n\t\tlegacyRedirects\n\t\treturnErrorValuesAsNull\n\n"
        f"ref expression Ruta\n\n{refs}\n", encoding="utf-8")
    ruta = str(PBI_DATA).replace("/", "\\").rstrip("\\") + "\\"
    (d / "expressions.tmdl").write_text(
        f'expression Ruta = "{ruta}" meta [IsParameterQuery = true, Type = "Text", IsParameterQueryRequired = true]\n'
        f"\tlineageTag: {uuid.uuid4()}\n\n\tannotation PBI_ResultType = Text\n", encoding="utf-8")
    for n, df in tablas.items():
        (d / "tables" / f"{n}.tmdl").write_text(tmdl_tabla(n, df), encoding="utf-8")
    (d / "relationships.tmdl").write_text(
        f"relationship {uuid.uuid4()}\n\tfromColumn: Episodios.fecha\n\ttoColumn: Fecha.fecha\n\n"
        f"relationship {uuid.uuid4()}\n\tfromColumn: OcupacionDiaria.fecha\n\ttoColumn: Fecha.fecha\n", encoding="utf-8")


# ----------------------------------------------------------------------------- reporte (PBIR)
SCH = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"


def lit(v):
    if isinstance(v, bool):
        return {"expr": {"Literal": {"Value": "true" if v else "false"}}}
    if isinstance(v, (int, float)):
        return {"expr": {"Literal": {"Value": f"{v}D"}}}
    return {"expr": {"Literal": {"Value": "'" + str(v).replace("'", "''") + "'"}}}


def campo(ref: str) -> dict:
    """'T[col]' → columna · 'M:Medida' → medida · 'Alias=ref' → con nombre visible."""
    if "=" in ref:
        alias, ref = ref.split("=", 1)
        out = campo(ref)
        out["displayName"] = alias
        return out
    if ref.startswith("M:"):
        m = ref[2:]
        return {"field": {"Measure": {"Expression": {"SourceRef": {"Entity": "Episodios"}}, "Property": m}},
                "queryRef": f"Episodios.{m}", "nativeQueryRef": m}
    t, c = ref.split("[")
    c = c.rstrip("]")
    agg = None
    if c.startswith("SUM:") or c.startswith("AVG:") or c.startswith("MAX:"):
        agg, c = c[:3], c[4:]
    col = {"Column": {"Expression": {"SourceRef": {"Entity": t}}, "Property": c}}
    if agg:
        f = {"SUM": 0, "AVG": 1, "MAX": 4}[agg]
        name = {"SUM": "Sum", "AVG": "Average", "MAX": "Max"}[agg]
        return {"field": {"Aggregation": {"Expression": col, "Function": f}},
                "queryRef": f"{name}({t}.{c})", "nativeQueryRef": f"{name} of {c}"}
    return {"field": col, "queryRef": f"{t}.{c}", "nativeQueryRef": c}


def visual(tipo, x, y, w, h, titulo, roles: dict, objects=None, z=0, sort=None, totales=True):
    vid = uuid.uuid4().hex[:20]
    v = {"$schema": f"{SCH}/visualContainer/2.4.0/schema.json", "name": vid,
         "position": {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": z},
         "visual": {"visualType": tipo,
                    "query": {"queryState": {r: {"projections": [campo(f) for f in fs]} for r, fs in roles.items()}},
                    "visualContainerObjects": {"title": [{"properties": {"show": lit(True), "text": lit(titulo)}}]},
                    "drillFilterOtherVisuals": True}}
    if sort:
        ref, direc = sort
        v["visual"]["query"]["sortDefinition"] = {"sort": [{"field": campo(ref)["field"], "direction": direc}],
                                                  "isDefaultSort": True}
    if not totales:
        objects = dict(objects or {})
        objects["total"] = [{"properties": {"totals": lit(False)}}]
    if objects:
        v["visual"]["objects"] = objects
    return vid, v


def texto(x, y, w, h, titulo, sub, z=0):
    vid = uuid.uuid4().hex[:20]
    para = lambda t, size, bold: {"textRuns": [{"value": t, "textStyle": {"fontSize": f"{size}pt", "color": "#FFFFFF",
                                                                          **({"fontWeight": "bold"} if bold else {})}}]}
    return vid, {"$schema": f"{SCH}/visualContainer/2.4.0/schema.json", "name": vid,
                 "position": {"x": x, "y": y, "z": z, "height": h, "width": w, "tabOrder": z},
                 "visual": {"visualType": "textbox",
                            "objects": {"general": [{"properties": {"paragraphs": [para(titulo, 17, True), para(sub, 10, False)]}}]},
                            "visualContainerObjects": {"background": [{"properties": {"show": lit(False)}}],
                                                       "border": [{"properties": {"show": lit(False)}}]}}}


def paginas() -> list[tuple[str, list]]:
    M = lambda m: "M:" + m
    P = []
    # 1 Resumen
    v = [texto(24, 4, 1232, 78, "Resumen ejecutivo",
               "El cuello de botella está en la salida de urgencias: quien necesita cama espera una mediana de 16,7 h.")]
    cards = [("Episodios por día", M("Episodios por día")), ("Espera de cama · mediana (h)", M("Espera de cama mediana (h)")),
             ("Espera de cama · P90 (h)", M("Espera de cama P90 (h)")), ("% hospitalizados", M("% hospitalizados")),
             ("Observación · mediana (h)", M("Observación mediana (h)")), ("% reconsulta 72 h", M("% reconsulta 72 h"))]
    for i, (t, f) in enumerate(cards):
        v.append(visual("card", 24 + i * 206, 92, 194, 110, t, {"Values": [f]}, z=i + 1))
    v.append(visual("lineClusteredColumnComboChart", 24, 216, 800, 480, "Episodios por mes y espera de cama (h)",
                    {"Category": ["Fecha[anio_mes]"], "Y": [M("Episodios")], "Y2": [M("Espera de cama mediana (h)")]}, z=10,
                    sort=("Fecha[anio_mes]", "Ascending")))
    v.append(visual("donutChart", 840, 216, 416, 300, "Tipo de episodio",
                    {"Category": ["Episodios[tipo_detalle]"], "Y": [M("Episodios válidos")]}, z=11))
    v.append(visual("slicer", 840, 528, 416, 168, "Año", {"Values": ["Fecha[anio]"]}, z=12))
    P.append(("Resumen", v))
    # 2 Flujo
    v = [texto(24, 4, 1232, 78, "Flujo y cuellos de botella",
               "El triage dura unos 3 minutos; el tiempo se acumula en observación y, sobre todo, esperando cama.")]
    v.append(visual("clusteredBarChart", 24, 92, 610, 290, "Estancia mediana por tipo de episodio (h)",
                    {"Category": ["Episodios[tipo_detalle]"], "Y": [M("Estancia mediana (h)")]}, z=1))
    v.append(visual("clusteredColumnChart", 646, 92, 610, 290, "Distribución de la espera de cama (episodios)",
                    {"Category": ["Episodios[rango_espera_cama]"], "Y": [M("Hospitalizados desde urgencias")]}, z=2,
                    sort=("Episodios[rango_espera_cama]", "Ascending")))
    v.append(visual("tableEx", 24, 394, 610, 302, "Trayectorias más frecuentes",
                    {"Values": ["Trayectoria=Variantes[variante]", "Episodios=Variantes[SUM:n]", "%=Variantes[SUM:pct]"]}, z=3,
                    sort=("Variantes[SUM:n]", "Descending"), totales=False))
    v.append(visual("tableEx", 646, 394, 610, 302, "Transiciones entre etapas",
                    {"Values": ["De=Transiciones[etapa_anterior]", "A=Transiciones[etapa]", "Pasos=Transiciones[SUM:n]"]}, z=4,
                    sort=("Transiciones[SUM:n]", "Descending"), totales=False))
    P.append(("Flujo", v))
    # 3 Congestión
    v = [texto(24, 4, 1232, 78, "Congestión",
               "Llegadas pico lunes y martes a las 10-11 h; la ocupación llega a su máximo unas 5 h después.")]
    v.append(visual("clusteredColumnChart", 24, 92, 610, 290, "Episodios por hora de llegada",
                    {"Category": ["Episodios[hora_llegada]"], "Y": [M("Episodios")]}, z=1, sort=("Episodios[hora_llegada]", "Ascending")))
    v.append(visual("clusteredColumnChart", 646, 92, 610, 290, "Pacientes en urgencias por hora (promedio)",
                    {"Category": ["Hora=OcupacionHora[hora_txt]"], "Y": [M("Pacientes en urgencias (promedio)")]}, z=2,
                    sort=("OcupacionHora[hora_txt]", "Ascending")))
    v.append(visual("lineChart", 24, 394, 610, 302, "Pico diario de ocupación vs umbral P90",
                    {"Category": ["OcupacionDiaria[fecha]"], "Y": ["Pico diario (media 28 días)=OcupacionDiaria[MAX:media_28d]", "Umbral de saturación (P90)=OcupacionDiaria[MAX:umbral_p90]"]}, z=3))
    v.append(visual("lineChart", 646, 394, 610, 302, "La congestión alarga la espera de cama (h, por decil de ocupación)",
                    {"Category": ["Congestion[decil]"], "Y": ["Espera de cama=Congestion[SUM:espera_cama_h]", "Estancia en observación=Congestion[SUM:estancia_observacion_h]"]}, z=4))
    P.append(("Congestión", v))
    # 4 Factores
    v = [texto(24, 4, 1232, 78, "Factores de demora",
               "La estancia prolongada se explica por lo que pasa dentro de urgencias: AUC 0,80 con todo el episodio frente a 0,60 al ingreso.")]
    v.append(visual("clusteredBarChart", 24, 92, 610, 296, "Estancia prolongada: qué la explica (SHAP, AUC 0,80)",
                    {"Category": ["ShapEstancia[variable]"], "Y": ["Importancia=ShapEstancia[SUM:importancia_shap]"]}, z=1,
                    sort=("ShapEstancia[SUM:importancia_shap]", "Descending")))
    v.append(visual("clusteredBarChart", 24, 400, 610, 296, "Hospitalización al ingreso (SHAP, AUC 0,77)",
                    {"Category": ["ShapHospitalizacion[variable]"], "Y": ["Importancia=ShapHospitalizacion[SUM:importancia_shap]"]}, z=2,
                    sort=("ShapHospitalizacion[SUM:importancia_shap]", "Descending")))
    v.append(visual("tableEx", 646, 92, 610, 300, "Diagnósticos más frecuentes",
                    {"Values": ["Diagnóstico=PerfilDx[dx_principal_nombre]", "Episodios=PerfilDx[SUM:episodios]", "Estancia mediana (h)=PerfilDx[SUM:estancia_p50_h]", "% hospitalizado=PerfilDx[SUM:pct_hospitalizado]"]}, z=3,
                    sort=("PerfilDx[SUM:episodios]", "Descending"), totales=False))
    v.append(visual("clusteredColumnChart", 646, 404, 610, 292, "% hospitalizados por grupo de edad",
                    {"Category": ["Episodios[grupo_edad]"], "Y": [M("% hospitalizados")]}, z=4, sort=("Episodios[grupo_edad]", "Ascending")))
    P.append(("Factores", v))
    # 5 Pronóstico
    v = [texto(24, 4, 1232, 78, "Pronóstico y alerta",
               "Llegadas del día siguiente con un error de 13,6 % (Holt-Winters). Alerta de saturación con AUC 0,92.")]
    v.append(visual("lineChart", 24, 92, 830, 330, "Llegadas diarias: real vs pronóstico",
                    {"Category": ["Pronostico[fecha]"], "Y": ["Real=Pronostico[SUM:llegadas_real]", "Holt-Winters=Pronostico[SUM:pred_holt_winters]", "LightGBM=Pronostico[SUM:pred_lightgbm]"]}, z=1))
    v.append(visual("tableEx", 866, 92, 390, 330, "Error por modelo",
                    {"Values": ["Modelo=MetricasPronostico[modelo]", "Error medio=MetricasPronostico[SUM:mae]", "MAPE %=MetricasPronostico[SUM:mape]"]}, z=2,
                    sort=("MetricasPronostico[SUM:mape]", "Ascending"), totales=False))
    v.append(visual("clusteredColumnChart", 24, 434, 1232, 262, "Probabilidad de saturación del día siguiente (%)",
                    {"Category": ["Pronostico[fecha]"], "Y": ["Probabilidad %=Pronostico[SUM:prob_saturacion]"]}, z=3))
    P.append(("Pronóstico", v))
    # 6 Escenarios
    v = [texto(24, 4, 1232, 78, "Escenarios what-if",
               "Simulación de la cola de camas (≈273 camas efectivas). Sirve para comparar medidas, no para predecir cifras exactas.")]
    v.append(visual("clusteredBarChart", 24, 92, 560, 604, "Espera media simulada por cama (h; barra recortada en 16 h)",
                    {"Category": ["Escenarios[escenario]"], "Y": ["Espera media (h)=Escenarios[SUM:espera_grafico_h]"]}, z=1,
                    sort=("Escenarios[SUM:espera_grafico_h]", "Descending")))
    v.append(visual("tableEx", 596, 92, 660, 604, "Recomendaciones",
                    {"Values": ["#=Recomendaciones[prioridad]", "Recomendación=Recomendaciones[recomendacion]", "Impacto esperado=Recomendaciones[impacto]"]}, z=2,
                    totales=False))
    P.append(("Escenarios", v))
    return P


def escribir_reporte() -> None:
    rp = PBI_DIR / f"{NAME}.Report"
    d = rp / "definition"
    if d.exists():
        shutil.rmtree(d)
    (d / "pages").mkdir(parents=True)
    (rp / "definition.pbir").write_text(json.dumps(
        {"version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}}, indent=2), encoding="utf-8")
    (d / "version.json").write_text(json.dumps(
        {"$schema": f"{SCH}/versionMetadata/1.0.0/schema.json", "version": "2.0.0"}, indent=2), encoding="utf-8")
    # tema registrado dentro del reporte
    res = rp / "StaticResources" / "RegisteredResources"
    res.mkdir(parents=True, exist_ok=True)
    (res / "HUN_Clinico.json").write_text(json.dumps(tema(), ensure_ascii=False), encoding="utf-8")
    (d / "report.json").write_text(json.dumps({
        "$schema": f"{SCH}/report/1.2.0/schema.json",
        "themeCollection": {"customTheme": {"name": "HUN_Clinico.json", "reportVersionAtImport": "5.59", "type": "RegisteredResources"}},
        "resourcePackages": [{"name": "RegisteredResources", "type": "RegisteredResources",
                              "items": [{"name": "HUN_Clinico.json", "path": "HUN_Clinico.json", "type": "CustomTheme"}]}],
        "layoutOptimization": "None",
        "settings": {"useStylableVisualContainerHeader": True, "defaultDrillFilterOtherVisuals": True},
    }, indent=2), encoding="utf-8")
    orden = []
    for nombre, visuales in paginas():
        pid = uuid.uuid4().hex[:20]
        orden.append(pid)
        pd_ = d / "pages" / pid
        (pd_ / "visuals").mkdir(parents=True)
        (pd_ / "page.json").write_text(json.dumps({
            "$schema": f"{SCH}/page/2.0.0/schema.json", "name": pid, "displayName": nombre,
            "displayOption": "FitToPage", "height": 720, "width": 1280}, ensure_ascii=False, indent=2), encoding="utf-8")
        for vid, v in visuales:
            (pd_ / "visuals" / vid).mkdir()
            (pd_ / "visuals" / vid / "visual.json").write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "pages" / "pages.json").write_text(json.dumps({
        "$schema": f"{SCH}/pagesMetadata/1.0.0/schema.json", "pageOrder": orden, "activePageName": orden[0]}, indent=2), encoding="utf-8")


def main():
    print("Tablas para Power BI…")
    tablas = preparar_datos()
    escribir_modelo(tablas)
    escribir_reporte()
    (PBI_DIR / f"{NAME}.pbip").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}],
        "settings": {"enableAutoRecovery": True}}, indent=2), encoding="utf-8")
    (PBI_DIR / "tema_HUN_clinico.json").write_text(json.dumps(tema(), ensure_ascii=False, indent=1), encoding="utf-8")
    gi = PBI_DIR / ".gitignore"
    gi.write_text("**/.pbi/localSettings.json\n**/.pbi/cache.abf\n", encoding="utf-8")
    print(f"✔ Proyecto: {PBI_DIR / (NAME + '.pbip')}")


if __name__ == "__main__":
    main()
