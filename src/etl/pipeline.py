from . import transform
from . import load
from . import extract
from src.config import DB_PATH


def run_pbp_etl_pipeline():
    print(f"--- Starting ETL ---")
    dirs = ['./data/']
    raw = extract.extract_dirs(dirs)
    pbps, matches, teams, players, comp = transform.transform_pbp_data(raw)
    load.load_data_to_db(pbps, matches, teams, players, comp, DB_PATH)
    print("--- Finished ---")
    return pbps, matches, teams, players, comp