import logging
from typing import Optional
from datetime import datetime
from prefect import flow, task

from src.config import get_logger

@task
def analytics_processing():
    from src.analytics.extract import extract_silver_data
    from src.analytics.transform import transform_to_gold
    from src.analytics.load import load_gold_data

    logger = get_logger()
    
    # 1. Extract
    silver_data = extract_silver_data()
    
    if silver_data['matches'].empty:
        logger.info("No matches found in Silver layer to process.")
        return "no_data"
        
    # 2. Transform
    gold_data = transform_to_gold(silver_data)
    
    # 3. Load
    load_gold_data(gold_data)
    
    logger.info("Successfully processed and loaded Gold/Analytics layer.")
    return "success"

@flow(name="cabb_analytics_gold")
def analytics_flow(ref_date: Optional[str] = None):
    """
    Capa Gold: Generación de tablas de hechos y dimensiones para analítica OLAP (Parquet).
    """
    logger = get_logger()
    if not ref_date:
        ref_date = datetime.now().strftime("%Y-%m-%d")

    logger.info(f"Procesamiento Analytics (Gold) iniciado (Ref Date: {ref_date})")

    # Run the processing task
    analytics_processing()

if __name__ == "__main__":
    analytics_flow()
