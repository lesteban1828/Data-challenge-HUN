"""Carga de las tablas OMOP desde data/raw (CSV, Parquet o Excel)."""
from pathlib import Path

import pandas as pd

from .config import DATA_RAW, DATETIME_COLS

TABLES = list(DATETIME_COLS.keys())
_READERS = {
    ".csv": pd.read_csv,
    ".parquet": pd.read_parquet,
    ".xlsx": pd.read_excel,
    ".xls": pd.read_excel,
}


def _find_file(table: str, folder: Path) -> Path | None:
    """Busca un archivo cuyo nombre contenga el nombre de la tabla (sin importar mayúsculas)."""
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() in _READERS and table in f.stem.lower():
            # evita que 'visit_occurrence' coincida con 'preceding_visit_occurrence', etc.
            if table == "visit_occurrence" and "detail" in f.stem.lower():
                continue
            return f
    return None


def load_table(table: str, folder: Path = DATA_RAW) -> pd.DataFrame:
    path = _find_file(table, folder)
    if path is None:
        raise FileNotFoundError(f"No encontré un archivo para '{table}' en {folder}")
    df = _READERS[path.suffix.lower()](path)
    df.columns = [c.strip().lower() for c in df.columns]
    for col in DATETIME_COLS.get(table, []):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def load_all(folder: Path = DATA_RAW, verbose: bool = True) -> dict[str, pd.DataFrame]:
    """Carga todas las tablas disponibles. Las que no existan se omiten con aviso."""
    tables = {}
    for t in TABLES:
        try:
            tables[t] = load_table(t, folder)
            if verbose:
                print(f"✔ {t:<22} {tables[t].shape[0]:>10,} filas  {tables[t].shape[1]} columnas")
        except FileNotFoundError as e:
            if verbose:
                print(f"✘ {e}")
    return tables
