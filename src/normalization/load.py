import pandas as pd
import os
import traceback
from datetime import datetime, timedelta
from src.config import S3_CURATED_PREFIX, get_logger
from src.utils import write_to_s3_parquet

logger = get_logger()

def load_data_to_db(pbps, matches, teams, players, competitions, DB_PATH=None):
    """
    Saves the data to S3 Curated zone in single files. 
    """
    stats = {}
    try:
        # --- 1. Global Entities (Upsert) ---
        stats['teams'] = write_to_s3_parquet(teams, S3_CURATED_PREFIX, 'teams', pk_columns=['team_id'], upsert=True)
        stats['players'] = write_to_s3_parquet(players, S3_CURATED_PREFIX, 'players', pk_columns=['player_id'], upsert=True)
        stats['competitions'] = write_to_s3_parquet(competitions, S3_CURATED_PREFIX, 'competitions', pk_columns=['id_comp'], upsert=True)

        # --- 2. Matches Processing ---
        if not matches.empty:
            upcoming_matches = matches[matches['status'] == 'NO_COMENZADO'].copy()
            played_matches = matches[matches['status'] != 'NO_COMENZADO'].copy()

            # Save Upcoming Matches (STRICT OVERWRITE)
            stats['upcoming_matches'] = write_to_s3_parquet(upcoming_matches, S3_CURATED_PREFIX, 'upcoming_matches', pk_columns=['match_id'], upsert=False)

            # Save Played Matches (Upsert)
            if not played_matches.empty:
                stats['matches'] = write_to_s3_parquet(played_matches, S3_CURATED_PREFIX, 'matches', pk_columns=['match_id'], upsert=True)

        # --- 3. PBPs Processing (Upsert) ---
        stats['pbps'] = write_to_s3_parquet(pbps, S3_CURATED_PREFIX, 'pbps', pk_columns=['pbp_id'], upsert=True)

        # --- Final Summary ---
        logger.info("="*40)
        logger.info("S3 CURATED ZONE UPDATE SUMMARY")
        logger.info("="*40)
        for entity, count in stats.items():
            mode = "Overwrite" if entity == 'upcoming_matches' else "Upsert (Total)"
            logger.info(f"- {entity.capitalize():<18}: {count:>6} records [{mode}]")
        logger.info("="*40)
        logger.info("EXITO: Zona Curated actualizada correctamente en S3.")

    except Exception as e:
        logger.error(f"PIPELINE STOPPED DUE TO S3 UPLOAD ERROR: {e}")
        raise

