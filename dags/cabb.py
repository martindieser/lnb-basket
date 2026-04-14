import os
import shutil
import random
import logging

from airflow.sdk import dag, task
from airflow.timetables.interval import CronDataIntervalTimetable
from datetime import datetime

from src.utils import get_season_id_from_date
from src.scrapers.cabb.sessions import Cache 
from src.scrapers.cabb.scraper import CABBScraper

from src.etl.extract import extract_dirs
from src.etl.transform import transform_pbp_data
from src.etl.load import load_data_to_db
from src.config import CABB_PATH 

logger = logging.getLogger(__name__)

@dag(
    schedule=CronDataIntervalTimetable("0 0 * * *", timezone="UTC"),
    start_date=datetime(2023, 1, 1), 
    max_active_tasks=2,
)
def cabb_scraping_workflow():

    # 1. Select Random Profile
    @task
    def get_random_profile():
        logger.info("Selecting a random profile...")
        all_profiles = Cache.available_profiles()
            
        selected = random.choice(all_profiles)
        logger.info(f"Selected Random Profile: {selected}")
        return selected

    # 2. Unified Scraping Phase
    @task
    def execute_scraping_phase(profile_id, selected_start, selected_end):
        logger.info(f"--- Starting Unified Scraping Phase (Profile: {profile_id}) ---")
        
        # Single instance, single session for the whole flow
        scraper = CABBScraper(profile_id)
        internal_cat_id = get_season_id_from_date(selected_start)
        
        # A. Resolve Category
        logger.info(f"Resolving Category ID for season {internal_cat_id}")
        cat_id = scraper.get_category_id("liga nacional", internal_cat_id)
        if not cat_id:
            raise ValueError(f"Category ID not found for season {internal_cat_id}")
            
        # B. Fetch Matches
        logger.info(f"Fetching matches between {selected_start} and {selected_end}")
        matches_data = scraper.fetch_matches(cat_id, selected_start, selected_end, internal_cat_id)
        
        if not matches_data:
            logger.warning("No matches found in this range. Skipping PBP phase.")
            return "no_matches"

        # C. Fetch PBPs
        logger.info(f"Fetching PBPs for {len(matches_data)} matches")
        scraper.fetch_pbp(matches_data, internal_cat_id)
        
        logger.info("--- Scraping Phase Completed Successfully ---")
        return "success"

    # 3. ETL Batch Processing
    @task
    def batch_processing(ref_date, upstream_status):
        if upstream_status == "no_matches":
            logger.info("Nothing to process, skipping ETL.")
            return

        season_id = get_season_id_from_date(ref_date)
        logger.info(f"Batch Processing season: {season_id}")
        
        # --- A. ETL ---
        raw_data = extract_dirs(CABB_PATH)
        stints, matches, teams, players, comp = transform_pbp_data(raw_data)
        load_data_to_db(stints, matches, teams, players, comp)


    # --- DAG FLOW ---
    selected_start = "{{ dag_run.conf.get('start_date', ds) }}"
    selected_end = "{{ dag_run.conf.get('end_date', macros.ds_add(dag_run.conf.get('start_date', ds), 7)) }}"

    # 1. Start: Get profile
    profile_id = get_random_profile()

    # 2. Extract: Run all scraping logic in one session
    scraping_status = execute_scraping_phase(
        profile_id=profile_id,
        selected_start=selected_start,
        selected_end=selected_end
    )

    # 3. Load: Run ETL after successful scraping
    batch_processing(ref_date=selected_start, upstream_status=scraping_status)

cabb_scraping_workflow()