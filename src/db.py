import os
import sqlite3
import duckdb
from src.config import (
    S3_BUCKET_NAME, 
    DATA_DIR, 
    AWS_ACCESS_KEY_ID, 
    AWS_SECRET_ACCESS_KEY, 
    AWS_REGION
)

def get_duckdb_conn():
    """
    Retorna una conexión de DuckDB configurada con el plugin HTTPFS 
    y las credenciales de S3 cargadas desde src.config para consultar 
    directamente los archivos Parquet.
    """
    con = duckdb.connect()
    
    if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
        try:
            con.execute("INSTALL httpfs; LOAD httpfs;")
            con.execute(f"SET s3_access_key_id='{AWS_ACCESS_KEY_ID}';")
            con.execute(f"SET s3_secret_access_key='{AWS_SECRET_ACCESS_KEY}';")
            con.execute(f"SET s3_region='{AWS_REGION}';")
        except Exception as e:
            print(f"Advertencia: No se pudo configurar el plugin httpfs de DuckDB: {e}")
            
    return con

def get_sqlite_conn(db_path=None):
    """
    Retorna una conexión a la base de datos SQLite local (database.db).
    """
    if db_path is None:
        db_path = os.path.join(DATA_DIR, "database.db")
    return sqlite3.connect(db_path)
