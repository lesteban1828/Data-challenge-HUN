# Conexión a la base de datos (FortiClient VPN + DBeaver + Python)

La base de datos solo es accesible dentro de la red del hospital/universidad. Siempre: **primero VPN, después DBeaver o Python.**

## 1. FortiClient VPN

1. Descargar **FortiClient VPN** (la versión gratuita "VPN-only") desde fortinet.com/support/product-downloads.
2. Abrir → *Configure VPN* → **SSL-VPN**.
   - Connection Name: `HUN Data Challenge`
   - Remote Gateway y Port: los que entregaron los organizadores.
   - Usuario/contraseña: los entregados.
3. *Connect*. Debe quedar en verde "VPN Connected".

## 2. DBeaver

1. *Database → New Database Connection* → elegir el motor que indiquen (PostgreSQL, SQL Server, …).
2. Host, Port, Database, Username, Password: los entregados.
3. *Test Connection* (la primera vez DBeaver descarga el driver).
4. Explorar con `sql/exploracion_dbeaver.sql`: conteos, fechas, conceptos y trayectorias de ejemplo.
5. Anotar: **motor**, **esquema** donde están las tablas y si existe la tabla **`concept`**.

## 3. Python (notebooks)

1. Copiar `.env.example` como `.env` y llenarlo con los mismos datos de DBeaver.
2. Instalar dependencias: `pip install -r requirements.txt`
   - SQL Server: instalar además "ODBC Driver 18 for SQL Server" y `pip install pyodbc`.
3. Probar (con la VPN conectada):
   ```powershell
   python -c "from src import db; db.test_connection(); print(db.row_counts())"
   ```
4. En la primera celda de cada notebook: `SOURCE = "db"`.
5. Correr una vez `db.concept_map()` para guardar los nombres de las etapas en `data/processed/concept_map.csv`.

La primera carga guarda una copia en `data/interim/` (no se sube a GitHub) para no depender de la VPN cada vez. Si las reglas del reto no permiten copias locales, usar `db.load_all(cache=False)`. Para probar rápido: `db.load_all(limit=50000)`.

## Problemas frecuentes

| Síntoma | Causa probable | Solución |
|---|---|---|
| Timeout / "could not connect" | VPN desconectada | Reconectar FortiClient |
| DBeaver conecta pero Python no | Falta el driver de Python | `pip install psycopg2-binary` / `pyodbc` / `pymysql` |
| "password authentication failed" | Error en `.env` | Copiar los datos exactos de DBeaver (Edit Connection) |
| "relation does not exist" | Esquema distinto | Poner `DB_SCHEMA` en `.env` |
| `concept_map()` falla | `concept` en otro esquema o inexistente | `DB_VOCAB_SCHEMA`, o pedir la tabla a los organizadores / usar Athena |
| Consulta muy lenta | Tabla grande (`measurement`) | `minimal=True` (por defecto), `limit=`, o agregar en SQL |

## Reglas

- Nunca subir `.env` ni datos a GitHub.
- No compartir credenciales por chats grupales; cada integrante con las suyas si las entregaron así.
