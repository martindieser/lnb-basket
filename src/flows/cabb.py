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

@task
def batch_processing(ref_date, upstream_status):
    if upstream_status == "no_matches":
        logger.info("Nothing to process, skipping ETL.")
        return

    import boto3
    from src.utils import get_season_id_from_date
    from src.etl.extract import extract_dirs, update_processed_registry
    from src.etl.transform import transform_pbp_data
    from src.etl.load import load_data_to_db

    # Extracción Incremental (solo archivos nuevos)
    raw_data, new_keys = extract_dirs()
    
    if not raw_data:
        logger.info("No new data to process in this run.")
        return

    # Transformación y Carga (con Upsert para no perder historial)
    pbps, matches, teams, players, comp = transform_pbp_data(raw_data)
    load_data_to_db(pbps, matches, teams, players, comp)

    # Registro de archivos procesados exitosamente
    s3_client = boto3.client('s3')
    update_processed_registry(s3_client, new_keys)
    logger.info(f"Successfully processed {len(new_keys)} new files and updated registry.")

@task
def generate_predictions_task(upstream_status):
    if upstream_status == "no_matches":
        logger.info("Nothing new to predict.")
        return
    
    from src.etl.predict import generate_predictions
    generate_predictions()

@flow(name="cabb_scraping_workflow")
def cabb_scraping_workflow(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None):
    """
    Workflow de scraping y procesamiento de datos de la CABB.
    Migrado de Airflow a Prefect.
    """
    # Lógica para fechas por defecto (reemplaza macros de Airflow)
    if not start_date:
        start_date = datetime.now().strftime("%Y-%m-%d")
    
    if not end_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_date = (start_dt + timedelta(days=7)).strftime("%Y-%m-%d")

    logger.info(f"Workflow iniciado para el rango: {start_date} - {end_date}")

    profile_id = get_random_profile()
    
    scraping_status = execute_scraping_phase(
        profile_id=profile_id,
        selected_start=start_date,
        selected_end=end_date,
    )
    
    # Procesamiento por lotes
    batch_processing_status = batch_processing(
        ref_date=start_date, 
        upstream_status=scraping_status
    )
    
    # Generación de predicciones (espera a que termine el procesamiento)
    generate_predictions_task(
        upstream_status=scraping_status, 
        wait_for=[batch_processing_status]
    )

if __name__ == "__main__":
    # Permite ejecución directa para pruebas locales
    cabb_scraping_workflow()
