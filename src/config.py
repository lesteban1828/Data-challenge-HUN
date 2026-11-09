"""Rutas y constantes del proyecto."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# Los datos viven FUERA del repo (el disco C: está lleno): por defecto D:/HUN_DataChallenge_datos.
# Se cambia con HUN_DATA_DIR en .env. Si D: no existe, se usa data/ dentro del repo.
_default = Path("D:/HUN_DataChallenge_datos") if Path("D:/").exists() else ROOT / "data"
DATA_DIR = Path(os.getenv("HUN_DATA_DIR") or _default)
DATA_RAW = DATA_DIR / "raw"
DATA_INTERIM = DATA_DIR / "interim"
DATA_PROCESSED = DATA_DIR / "processed"
FIGURES = ROOT / "reports" / "figures"
MODELS = ROOT / "models"

for _p in (DATA_RAW, DATA_INTERIM, DATA_PROCESSED, FIGURES, MODELS):
    _p.mkdir(parents=True, exist_ok=True)

# Columnas de fecha por tabla (según las bases del reto)
DATETIME_COLS = {
    "person": [],
    "visit_occurrence": ["visit_start_datetime", "visit_end_datetime"],
    "visit_detail": ["visit_detail_start_datetime", "visit_detail_end_datetime"],
    "condition_occurrence": ["condition_start_datetime"],
    "procedure_occurrence": ["procedure_datetime"],
    "measurement": ["measurement_datetime"],
}

# Conceptos OMOP estándar frecuentes (VERIFICAR con los datos reales)
VISIT_CONCEPTS = {
    9201: "Hospitalización",
    9202: "Ambulatoria",
    9203: "Urgencias",
    262: "Urgencias + Hospitalización",
}
GENDER_CONCEPTS = {8507: "Masculino", 8532: "Femenino"}

RANDOM_STATE = 42

# ---- Datos reales del reto (esquema uninorte_omop) ----
# Etapas de visit_detail. Nombres en español = interpretación del equipo (verificar con el hospital).
ETAPAS = {
    9203: "Ingreso urgencias (triage)",
    3045729: "Atención en urgencias",
    9201: "Hospitalización",
    581479: "Consulta ambulatoria",
}
ETAPAS_URGENCIAS = (9203, 3045729, 9201)
GAP_EPISODIO_H = 6            # etapas separadas por más de esto = episodio distinto
FECHA_INICIO = "2023-01-01"
FECHA_CORTE = "2026-05-01"    # desde mayo-2026 la carga está incompleta
