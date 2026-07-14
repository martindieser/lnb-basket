import logging
from typing import Optional
from datetime import datetime
from prefect import flow, task

from src.config import get_logger

from dotenv import load_dotenv
from pathlib import Path

# env_path = Path(__file__).resolve().parent.parent.parent / ".env"
# load_dotenv(env_path)

@task
def batch_processing(ref_date):
    import boto3
    from src.normalization.extract import (
        extract_dirs, 
        update_processed_registry,
        extract_proballers_details
    )
    from src.normalization.transform import transform_pbp_data
    from src.normalization.load import load_data_to_db

    logger = get_logger()
    
    # Extracción de detalles de jugadores desde S3
    logger.info("Extracting Proballers player details from S3...")
    players_details = extract_proballers_details()
    
    # Extracción Incremental (solo archivos nuevos)
    raw_data, new_keys = extract_dirs()
    
    if not raw_data:
        logger.info("No new data to process in this run.")
        return "no_new_data"

    # Transformación y Carga (con Upsert para no perder historial)
    pbps, matches, teams, players, comp = transform_pbp_data(raw_data, players_details)
    load_data_to_db(pbps, matches, teams, players, comp)

    # Registro de archivos procesados exitosamente
    s3_client = boto3.client('s3')
    update_processed_registry(s3_client, new_keys)
    logger.info(f"Successfully processed {len(new_keys)} new files and updated registry.")
    return "success"

@flow(name="cabb_normalization_silver")
def normalization_flow(ref_date: Optional[str] = None):
    """
    Capa Silver: Transformación de datos crudos a formato relacional normalizado (Parquet).
    """

    logger = get_logger()
    if not ref_date:
        ref_date = datetime.now().strftime("%Y-%m-%d")

    logger.info(f"Normalización iniciada (Ref Date: {ref_date})")

    # Procesamiento por lotes (Bronze -> Silver)
    batch_processing(ref_date=ref_date)

if __name__ == "__main__":
    normalization_flow()
