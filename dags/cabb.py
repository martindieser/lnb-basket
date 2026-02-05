import os
import shutil
import random

from airflow.sdk import dag, task
from airflow.timetables.interval import CronDataIntervalTimetable
from datetime import datetime

from src.core.scrapers.cabb.lib import CABBTaskHandler, get_season_id_from_date
from src.core.scrapers.cabb.mapping import Cache 
from src.core.scrapers.cabb.client import CABBScraper

from src.core.etl.cabb.extract import extract_dirs
from src.core.etl.cabb.transform import transform_pbp_data
from src.core.etl.cabb.load import load_data_to_db
from src.core.config import DB_PATH, CABB_PATH 

@dag(
    schedule=CronDataIntervalTimetable("0 0 * * *", timezone="UTC"),
    start_date=datetime(2023, 1, 1), 
    max_active_tasks=2,
)
def cabb_scraping_workflow():

    # 1. Select Random Profile
    @task
    def get_random_profile():
        print("[AUDIT] Selecting a random profile...", flush=True)
        all_profiles = [id_ for id_ in Cache.available_profiles()]
        
        if len(all_profiles) < 5:
            client = CABBScraper()
            all_profiles = [id_ for id_ in Cache.available_profiles()]
        selected = random.choice(all_profiles)
        print(f"[AUDIT] Selected Random Profile: {selected}", flush=True)
        return selected

    # 2. Get Category ID
    @task
    def get_category_id(profile_id, ref_date) -> str:
        print(f"[AUDIT] Using profile {profile_id}", flush=True)
        internal_cat_id = get_season_id_from_date(ref_date)
        handler = CABBTaskHandler(profile_id, internal_catid=internal_cat_id)
        
        print(f"[AUDIT] Resolving Category ID for season {internal_cat_id}", flush=True)
        cat_id = handler.get_category_id("liga nacional")
        # if cat_id is None:
        #     handler.discover_categories("liga nacional")
        #     cat_id = handler.get_category_id(internal_cat_id)
        assert (cat_id is not None) and (cat_id != {}) and (cat_id != '{}'), "Category ID should not be None after discovery"
        return cat_id

    # 3. Scrape Matches
    @task
    def scrape_matches(date_from, date_to, cat_id, profile_id):
        internal_cat_id = get_season_id_from_date(date_from)
        print(f"--- [AUDIT START] Scrape Matches ({cat_id}) ---", flush=True)
        
        handler = CABBTaskHandler(profile_id, internal_catid=internal_cat_id)
        return handler.fetch_matches(cat_id, date_from, date_to)

    # 4. Scrape PBP
    @task
    def scrape_pbp(matches_dict, profile_id, selected_start):
        print(f"--- [AUDIT START] Scrape PBP for {profile_id} for {selected_start} ---", flush=True)
        internal_cat_id = get_season_id_from_date(selected_start)
        handler = CABBTaskHandler(profile_id, internal_catid=internal_cat_id)
        # El handler guarda los jsons en CABB_PATH internamente
        return handler.fetch_pbp(matches_dict)

    # 5. ETL Batch Processing (Extract -> Transform -> Load -> Move)
    @task
    def batch_processing(ref_date, upstream_trigger):
        season_id = get_season_id_from_date(ref_date)
        folder_name = f"pbp_{season_id}"
        print(f"--- Batch Processing: {season_id} ---")
        source_dir = CABB_PATH
        # --- A. ETL ---
        print(f"-> Extracting from: {source_dir}")
        raw_data = extract_dirs(source_dir)
        
        print("-> Transforming PBP data...")
        pbps, matches, teams, players, comp = transform_pbp_data(raw_data)
        
        print(f"-> Loading to DB: {DB_PATH}")
        load_data_to_db(pbps, matches, teams, players, comp, DB_PATH)


    # --- DAG FLOW ---
    # selected_start = "{{ data_interval_start | ds }}"
    # selected_end = "{{ data_interval_end | ds }}"
    # Inicio: Usa 'start_date' o la fecha de ejecución (ds)
    selected_start = "{{ dag_run.conf.get('start_date', ds) }}"
    
    selected_end = "{{ dag_run.conf.get('end_date', macros.ds_add(dag_run.conf.get('start_date', ds), 7)) }}"

    # Scraper Logic
    profile_id = get_random_profile()
    cat_id = get_category_id(profile_id, selected_start)

    matches_data = scrape_matches(
        date_from=selected_start,
        date_to=selected_end,
        cat_id=cat_id,
        profile_id=profile_id
    )

    pbp_result = scrape_pbp(matches_data, profile_id, selected_start)

    # ETL Logic (Runs after scraper finishes)
    batch_processing(ref_date=selected_start, upstream_trigger=pbp_result)

cabb_scraping_workflow()