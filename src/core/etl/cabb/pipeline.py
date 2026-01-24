import sqlite3
from .transform import transform_pbp_data
from .load import load_data_to_db
from ...config import DB_PATH


def run_pbp_etl_pipeline():
    print(f"--- Starting ETL ---")
    dirs = ['./data/']
    raw = extract_dirs(dirs)
    pbps, matches, teams, players, comp = transform_pbp_data(raw)
    load_data_to_db(pbps, matches, teams, players, comp, DB_PATH)
    print("--- Finished ---")
    return pbps, matches, teams, players, comp