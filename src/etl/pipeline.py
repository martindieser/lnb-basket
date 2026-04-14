from . import transform
from . import load
from . import extract


def run_pbp_etl_pipeline():
    print(f"--- Starting ETL ---")
    dirs = ['./data/']
    raw = extract.extract_dirs(dirs)
    stints, matches, teams, players, comp = transform.transform_pbp_data(raw)
    load.load_data_to_db(stints, matches, teams, players, comp)
    print("--- Finished ---")
    return stints, matches, teams, players, comp