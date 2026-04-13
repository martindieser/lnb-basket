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
from src.config import DB_PATH, CABB_PATH 

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
        
        if len(all_profiles) < 5:
            CABBScraper() # Trigger registration if needed
            all_profiles = Cache.available_profiles()
            
        selected = random.choice(all_profiles)
        logger.info(f"Selected Random Profile: {selected}")
        return selected

    # 2. Get Category ID
    @task
    def get_category_id(profile_id, ref_date) -> str:
        logger.info(f"Using profile {profile_id}")
        internal_cat_id = get_season_id_from_date(ref_date)
        scraper = CABBScraper(profile_id)
        
        logger.info(f"Resolving Category ID for season {internal_cat_id}")
        cat_id = scraper.get_category_id("liga nacional", internal_cat_id)
        
        if not cat_id:
            raise ValueError(f"Category ID not found for season {internal_cat_id}")
            
        return cat_id

    # 3. Scrape Matches
    @task
    def scrape_matches(date_from, date_to, cat_id, profile_id):
        internal_cat_id = get_season_id_from_date(date_from)
        logger.info(f"Scraping matches for {internal_cat_id}")
        
        scraper = CABBScraper(profile_id)
        return scraper.fetch_matches(cat_id, date_from, date_to, internal_cat_id)

    # 4. Scrape PBP
    @task
    def scrape_pbp(matches_dict, profile_id, selected_start):
        logger.info(f"Scraping PBP for {profile_id}")
        internal_cat_id = get_season_id_from_date(selected_start)
        scraper = CABBScraper(profile_id)
        return scraper.fetch_pbp(matches_dict, internal_cat_id)

    # 5. ETL Batch Processing
    @task
    def batch_processing(ref_date, upstream_trigger):
        season_id = get_season_id_from_date(ref_date)
        logger.info(f"Batch Processing season: {season_id}")
        
        # --- A. ETL ---
        raw_data = extract_dirs(CABB_PATH)
        pbps, matches, teams, players, comp = transform_pbp_data(raw_data)
        load_data_to_db(pbps, matches, teams, players, comp, DB_PATH)


    # --- DAG FLOW ---
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

    # ETL Logic
    batch_processing(ref_date=selected_start, upstream_trigger=pbp_result)

cabb_scraping_workflow()