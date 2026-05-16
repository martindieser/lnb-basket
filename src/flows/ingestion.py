import logging
import random
from typing import Optional
from datetime import datetime, timedelta
from prefect import flow, task

from dotenv import load_dotenv
from pathlib import Path

env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(env_path)

# Configurar logging básico para visibilidad en Prefect
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@task
def get_random_profile():
    from src.scrapers.cabb.sessions import Cache

    logger.info("Selecting a random profile...")
    all_profiles = Cache.available_profiles()
    if not all_profiles:
        logger.warning("No profiles available. A new one will be created during scraper initialization.")
        return None

    selected = random.choice(all_profiles)
    logger.info(f"Selected Random Profile: {selected}")
    return selected

@task
def execute_scraping_phase(profile_id, selected_start, selected_end):
    from src.utils import get_season_id_from_date
    from src.scrapers.cabb.scraper import CABBScraper

    logger.info(f"--- Starting Unified Scraping Phase (Profile: {profile_id}) ---")

    scraper = CABBScraper(profile_id)
    internal_cat_id = get_season_id_from_date(selected_start)

    logger.info(f"Resolving Category ID for season {internal_cat_id}")
    cat_id = scraper.get_category_id("liga nacional", internal_cat_id)
    if not cat_id:
        raise ValueError(f"Category ID not found for season {internal_cat_id}")

    logger.info(f"Fetching matches between {selected_start} and {selected_end}")
    matches_data = scraper.fetch_matches(cat_id, selected_start, selected_end, internal_cat_id)

    if not matches_data:
        logger.warning("No matches found in this range. Skipping PBP phase.")
        return "no_matches"

    logger.info(f"Fetching PBPs for {len(matches_data)} matches")
    scraper.fetch_pbp(matches_data, internal_cat_id)

    logger.info("--- Scraping Phase Completed Successfully ---")
    return "success"

@flow(name="cabb_ingestion_bronze")
def ingestion_flow(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None):
    """
    Capa Bronze: Recolección de datos crudos desde CABB y almacenamiento en S3 (JSON).
    """
    if not start_date:
        start_date = datetime.now().strftime("%Y-%m-%d")
    
    if not end_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_date = (start_dt + timedelta(days=7)).strftime("%Y-%m-%d")

    logger.info(f"Ingesta iniciada para el rango: {start_date} - {end_date}")

    profile_id = get_random_profile()
    
    execute_scraping_phase(
        profile_id=profile_id,
        selected_start=start_date,
        selected_end=end_date,
    )

if __name__ == "__main__":
    ingestion_flow()
