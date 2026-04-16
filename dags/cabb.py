import logging
import random
from datetime import datetime
from airflow.decorators import dag, task

logger = logging.getLogger(__name__)

@dag(
    schedule="0 0 * * *",  
    start_date=datetime(2023, 1, 1),
    max_active_tasks=2,
    catchup=False
)
def cabb_scraping_workflow():

    @task
    def get_random_profile():
        from src.scrapers.cabb.sessions import Cache

        logger.info("Selecting a random profile...")
        all_profiles = Cache.available_profiles()
        if not all_profiles:
            raise ValueError("No profiles available for scraping.")
            
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
        from src.config import CABB_PATH
        from src.etl.extract import extract_dirs, update_processed_registry
        from src.etl.transform import transform_pbp_data
        from src.etl.load import load_data_to_db

        # Extracción Incremental (solo archivos nuevos)
        raw_data, new_keys = extract_dirs(CABB_PATH)
        
        if not raw_data:
            logger.info("No new data to process in this run.")
            return

        # Transformación y Carga (con Upsert para no perder historial)
        stints, matches, teams, players, comp = transform_pbp_data(raw_data)
        load_data_to_db(stints, matches, teams, players, comp)

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

    # --- DAG FLOW ---
    # Usamos macros de Airflow directamente en la llamada a las tareas
    selected_start = "{{ dag_run.conf.get('start_date', ds) }}"
    # Para el end_date usamos la lógica de Jinja directamente
    selected_end = "{{ dag_run.conf.get('end_date', macros.ds_add(dag_run.conf.get('start_date', ds), 7)) }}"

    profile_id = get_random_profile()
    scraping_status = execute_scraping_phase(
        profile_id=profile_id,
        selected_start=selected_start,
        selected_end=selected_end,
    )
    batch_processing_status = batch_processing(ref_date=selected_start, upstream_status=scraping_status)
    batch_processing_status >> generate_predictions_task(upstream_status=scraping_status)

cabb_scraping_workflow()