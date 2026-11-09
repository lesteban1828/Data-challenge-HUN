"""Conexión a la base de datos del reto.

Requisitos:
  1. FortiClient VPN conectada (sin VPN, la base de datos no responde).
  2. Archivo .env en la raíz del proyecto con las credenciales (ver .env.example).

Uso rápido:
    from src import db
    db.test_connection()
    db.list_tables()
    t = db.load_all()          # mismo formato que load.load_all()
    db.concept_map()           # nombres de los concept_id → data/processed/concept_map.csv
"""
import os
from functools import lru_cache

import pandas as pd

from .config import DATA_INTERIM, DATA_PROCESSED, DATETIME_COLS, ROOT

# Columnas mínimas que usan los notebooks (reduce lo que viaja por la VPN)
MIN_COLS = {
    "person": ["person_id", "gender_concept_id", "year_of_birth"],
    "visit_occurrence": ["visit_occurrence_id", "person_id", "visit_concept_id", "visit_start_datetime",
                         "visit_end_datetime", "visit_type_concept_id", "provider_id",
                         "preceding_visit_occurrence_id"],
    "visit_detail": ["visit_detail_id", "visit_occurrence_id", "visit_detail_concept_id",
                     "visit_detail_start_datetime", "visit_detail_end_datetime", "provider_id"],
    "condition_occurrence": ["condition_occurrence_id", "person_id", "visit_occurrence_id",
                             "condition_concept_id", "condition_start_datetime"],
    "procedure_occurrence": ["procedure_occurrence_id", "person_id", "visit_occurrence_id",
                             "procedure_concept_id", "procedure_datetime"],
    "measurement": ["measurement_id", "person_id", "visit_occurrence_id", "measurement_concept_id",
                    "measurement_datetime"],
}


def _load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass


@lru_cache(maxsize=1)
def engine():
    """Crea el engine de SQLAlchemy desde .env (DB_URL o DB_DIALECT/DB_HOST/...)."""
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL

    _load_env()
    url = os.getenv("DB_URL")
    if not url:
        missing = [k for k in ("DB_DIALECT", "DB_HOST", "DB_NAME", "DB_USER") if not os.getenv(k)]
        if missing:
            raise RuntimeError(f"Faltan variables en .env: {missing}. Copia .env.example como .env y llénalo.")
        query = {}
        if os.getenv("DB_DIALECT", "").startswith("mssql"):
            query = {"driver": os.getenv("DB_ODBC_DRIVER", "ODBC Driver 18 for SQL Server"),
                     "TrustServerCertificate": "yes"}
        # URL.create escapa automáticamente caracteres especiales de la contraseña
        url = URL.create(
            drivername=os.getenv("DB_DIALECT"),
            username=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            host=os.getenv("DB_HOST"),
            port=int(os.getenv("DB_PORT")) if os.getenv("DB_PORT") else None,
            database=os.getenv("DB_NAME"),
            query=query,
        )
    return create_engine(url, pool_pre_ping=True)


def _schema(vocab: bool = False) -> str | None:
    _load_env()
    if vocab and os.getenv("DB_VOCAB_SCHEMA"):
        return os.getenv("DB_VOCAB_SCHEMA")
    return os.getenv("DB_SCHEMA") or None


def test_connection() -> None:
    from sqlalchemy import text
    try:
        with engine().connect() as c:
            c.execute(text("SELECT 1"))
        print(f"✔ Conexión OK ({engine().dialect.name})")
    except Exception as e:
        print("✘ No se pudo conectar. ¿Está FortiClient VPN conectada? ¿Datos de .env iguales a DBeaver?")
        raise e


def list_tables(vocab: bool = False) -> list[str]:
    from sqlalchemy import inspect
    return sorted(inspect(engine()).get_table_names(schema=_schema(vocab)))


def _real_name(table: str, vocab: bool = False) -> str:
    """Nombre real de la tabla en la BD (sin importar mayúsculas), con su esquema."""
    names = {n.lower(): n for n in list_tables(vocab)}
    if table.lower() not in names:
        raise KeyError(f"La tabla '{table}' no está en el esquema '{_schema(vocab)}'. Disponibles: {list(names.values())}")
    name = engine().dialect.identifier_preparer.quote(names[table.lower()])
    s = _schema(vocab)
    return f"{engine().dialect.identifier_preparer.quote_schema(s)}.{name}" if s else name


def query(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Ejecuta un SELECT y devuelve un DataFrame con columnas en minúscula."""
    from sqlalchemy import text
    with engine().connect() as c:
        df = pd.read_sql(text(sql), c, params=params)
    df.columns = [col.lower() for col in df.columns]
    return df


def _select(table_sql: str, columns: list[str] | None, limit: int | None) -> str:
    cols = ", ".join(columns) if columns else "*"
    if limit and engine().dialect.name == "mssql":
        return f"SELECT TOP {int(limit)} {cols} FROM {table_sql}"
    return f"SELECT {cols} FROM {table_sql}" + (f" LIMIT {int(limit)}" if limit else "")


def load_table(table: str, minimal: bool = True, limit: int | None = None,
               cache: bool = True, refresh: bool = False) -> pd.DataFrame:
    """Lee una tabla OMOP desde la BD.

    minimal: solo las columnas que usan los notebooks (más rápido por la VPN).
    limit:   número máximo de filas (útil para pruebas rápidas).
    cache:   guarda una copia local en data/interim/ (gitignored) para no depender de la VPN
             en cada corrida. Ponerlo en False si las reglas del reto no permiten copias locales.
    """
    cache_file = DATA_INTERIM / f"db_{table}{'_min' if minimal else ''}{f'_{limit}' if limit else ''}.parquet"
    if cache and cache_file.exists() and not refresh:
        return pd.read_parquet(cache_file)

    tsql = _real_name(table)
    columns = None
    if minimal and table in MIN_COLS:
        from sqlalchemy import inspect
        real_cols = {c["name"].lower(): c["name"] for c in
                     inspect(engine()).get_columns(tsql.split(".")[-1].strip('"[]`'), schema=_schema())}
        columns = [engine().dialect.identifier_preparer.quote(real_cols[c])
                   for c in MIN_COLS[table] if c in real_cols]
    df = query(_select(tsql, columns, limit))
    for col in DATETIME_COLS.get(table, []):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    if cache:
        df.to_parquet(cache_file, index=False)
    return df


def load_all(minimal: bool = True, limit: int | None = None, cache: bool = True,
             refresh: bool = False, verbose: bool = True) -> dict[str, pd.DataFrame]:
    """Carga todas las tablas del reto desde la BD (mismo formato que load.load_all)."""
    tables = {}
    for t in DATETIME_COLS:
        try:
            tables[t] = load_table(t, minimal=minimal, limit=limit, cache=cache, refresh=refresh)
            if verbose:
                print(f"✔ {t:<22} {tables[t].shape[0]:>10,} filas  {tables[t].shape[1]} columnas")
        except KeyError as e:
            if verbose:
                print(f"✘ {e}")
    return tables


def row_counts() -> pd.DataFrame:
    """Conteo de filas de cada tabla del reto (sin descargar los datos)."""
    rows = []
    for t in DATETIME_COLS:
        try:
            n = query(f"SELECT COUNT(*) AS n FROM {_real_name(t)}")["n"].iloc[0]
            rows.append({"tabla": t, "filas": int(n)})
        except KeyError:
            rows.append({"tabla": t, "filas": None})
    return pd.DataFrame(rows)


def concept_map(save: bool = True) -> pd.DataFrame:
    """Busca en la tabla CONCEPT (si existe) los nombres de los concept_id usados en visitas y personas.

    Si CONCEPT está en otro esquema, definir DB_VOCAB_SCHEMA en .env.
    """
    concept = _real_name("concept", vocab=True)
    vo, vd, pe = _real_name("visit_occurrence"), _real_name("visit_detail"), _real_name("person")
    sql = f"""
        SELECT c.concept_id, c.concept_name, c.domain_id AS domain, c.vocabulary_id
        FROM {concept} c
        WHERE c.concept_id IN (
            SELECT visit_detail_concept_id FROM {vd}
            UNION SELECT visit_concept_id FROM {vo}
            UNION SELECT visit_type_concept_id FROM {vo}
            UNION SELECT gender_concept_id FROM {pe}
        )"""
    cm = query(sql)
    if save:
        cm.to_csv(DATA_PROCESSED / "concept_map.csv", index=False)
        print(f"✔ {len(cm)} conceptos guardados en data/processed/concept_map.csv")
    return cm
