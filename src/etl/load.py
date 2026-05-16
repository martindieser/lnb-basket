import pandas as pd
import os
import traceback
import logging
from datetime import datetime, timedelta
from src.config import S3_BUCKET_NAME, S3_CURATED_PREFIX

logger = logging.getLogger(__name__)

def write_to_s3_parquet(df, entity_name, pk_columns=None, upsert=True):
    """
    Writes a DataFrame to S3 as a single Parquet file.
    If upsert=True, it merges with existing data. If False, it overwrites.
    Returns: Final count of records saved.
    """
    if not S3_BUCKET_NAME or df.empty:
        return 0

    s3_path = f"s3://{S3_BUCKET_NAME}/{S3_CURATED_PREFIX}/{entity_name}/data.parquet"
    
    # 1. Attempt to load existing data for Upsert
    if upsert:
        try:
            existing_df = pd.read_parquet(s3_path, engine='pyarrow')
            df = pd.concat([existing_df, df], ignore_index=True)
        except Exception:
            # File doesn't exist, proceed with current df
            pass

    # 2. Cleanup of duplicates before writing
    if pk_columns:
        df = df.drop_duplicates(subset=pk_columns, keep='last')
        
    try:
        df.to_parquet(s3_path, index=False, engine='pyarrow')
        return len(df)
    except Exception as e:
        logger.error(f"CRITICAL ERROR: Failed to upload {entity_name} to S3: {e}")
        raise

def load_data_to_db(pbps, matches, teams, players, competitions, DB_PATH=None):
    """
    Saves the data to S3 Curated zone in single files. 
    """
    stats = {}
    try:
        # --- 1. Global Entities (Upsert) ---
        stats['teams'] = write_to_s3_parquet(teams, 'teams', pk_columns=['team_id'], upsert=True)
        stats['players'] = write_to_s3_parquet(players, 'players', pk_columns=['player_id'], upsert=True)
        stats['competitions'] = write_to_s3_parquet(competitions, 'competitions', pk_columns=['id_comp'], upsert=True)

        # --- 2. Matches Processing ---
        if not matches.empty:
            upcoming_matches = matches[matches['status'] == 'NO_COMENZADO'].copy()
            played_matches = matches[matches['status'] != 'NO_COMENZADO'].copy()

            # Save Upcoming Matches (STRICT OVERWRITE)
            stats['upcoming_matches'] = write_to_s3_parquet(upcoming_matches, 'upcoming_matches', pk_columns=['match_id'], upsert=False)

            # Save Played Matches (Upsert)
            if not played_matches.empty:
                stats['matches'] = write_to_s3_parquet(played_matches, 'matches', pk_columns=['match_id'], upsert=True)

        # --- 3. PBPs Processing (Upsert) ---
        stats['pbps'] = write_to_s3_parquet(pbps, 'pbps', pk_columns=['pbp_id'], upsert=True)

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
