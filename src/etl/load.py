import sqlite3
import pandas as pd
import os
import traceback
import logging

# --- NUEVA FUNCIÓN DE LIMPIEZA ---
def clean_ghost_matches(conn, days_tolerance=2):
    logger = logging.getLogger(__name__)
    cursor = conn.cursor()
    try:
        # Ajustá 'estado' y 'fecha' a los nombres reales de tus columnas en la DB
        sql_clean = f"""
        DELETE FROM matches
        WHERE (matches.status = 'NO_COMENZADO') 
        AND matches.date < date('now', '-{days_tolerance} days');
        """
        
        cursor.execute(sql_clean)
        deleted_count = cursor.rowcount
        if deleted_count > 0:
            print(f"🧹 LIMPIEZA: Se eliminaron {deleted_count} partidos fantasmas/reprogramados antiguos.")
            
    except Exception as e:
        print(f"⚠️ Warning: No se pudo ejecutar la limpieza de zombies: {e}")

def upsert_dataframe(df, table_name, conn, pk_columns):
    """
    Realiza un Upsert usando ON CONFLICT (Nativo de SQLite).
    NO borra registros, solo actualiza los existentes.
    """
    cursor = conn.cursor()
    
    # 1. Crear tabla temporal
    temp_table_name = f"temp_{table_name}"
    df.to_sql(temp_table_name, conn, if_exists='replace', index=False)

    # 2. Preparar partes de la query
    columns = list(df.columns)
    columns_str = ", ".join(columns)
    pk_str = ", ".join(pk_columns)
    
    # Crea la parte de: col1=excluded.col1, col2=excluded.col2
    # Solo actualizamos las columnas que NO son PK
    update_actions = ", ".join([f"{col}=excluded.{col}" for col in columns if col not in pk_columns])

    # 3. Query Nativa de UPSERT (Requiere SQLite 3.24+, año 2018 en adelante)
    upsert_sql = f"""
    INSERT INTO {table_name} ({columns_str})
    SELECT {columns_str} FROM {temp_table_name}
    WHERE true
    ON CONFLICT({pk_str}) DO UPDATE SET
    {update_actions};
    """
    
    try:
        cursor.execute(upsert_sql)
    finally:
        cursor.execute(f"DROP TABLE IF EXISTS {temp_table_name}")

def load_data_to_db(pbps, matches, teams, players, competitions, DB_PATH):
    """
    Carga datos. Realiza UPSERT para Equipos y Jugadores, 
    y APPEND estricto para el resto.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        cursor = conn.cursor()
        cursor.execute("BEGIN TRANSACTION;")

        # --- 1. UPSERT para Equipos ---
        print("Upserting Equipos...")
        upsert_dataframe(teams, 'teams', conn, pk_columns=['team_id'])

        # --- 2. UPSERT para Jugadores ---
        print("Upserting Jugadores...")
        upsert_dataframe(players, 'players', conn, pk_columns=['player_id'])

        # --- 3. Resto de tablas ---
        print("Upserting Competencias...")
        upsert_dataframe(competitions, 'competitions', conn, pk_columns=['id_comp'])

        print("Upserting Partidos...")
        # Primero insertamos los nuevos (incluyendo los reprogramados con fecha nueva)
        upsert_dataframe(matches, 'matches', conn, pk_columns=['match_id'])
        
        # >>> AQUI AGREGAMOS LA LIMPIEZA <<<
        # Una vez que los datos nuevos están listos, barremos la basura vieja
        clean_ghost_matches(conn, days_tolerance=2)
        
        print("Cargando Eventos (PBP)...")
        upsert_dataframe(pbps, 'pbps', conn, pk_columns=['pbp_id'])

        conn.commit()
        print("ÉXITO: Datos actualizados y cargados correctamente.")

    except Exception as e:
        conn.rollback()
        traceback.print_exc()
        raise
    finally:
        conn.close()