import pandas as pd
import os
import traceback
import logging
from datetime import datetime, timedelta
from src.config import S3_BUCKET_NAME, S3_CURATED_PREFIX

def write_to_s3_parquet(df, entity_name, pk_columns=None):
    """
    Writes a DataFrame to S3 as a single Parquet file, overwriting if exists.
    Raises exception if upload fails.
    """
    if not S3_BUCKET_NAME or df.empty:
        return

    s3_path = f"s3://{S3_BUCKET_NAME}/{S3_CURATED_PREFIX}/{entity_name}/data.parquet"
    
    # Internal cleanup of duplicates before writing
    if pk_columns:
        df = df.drop_duplicates(subset=pk_columns, keep='last')
        
    try:
        df.to_parquet(s3_path, index=False, engine='pyarrow')
        print(f"Saved {entity_name} to S3.")
    except Exception as e:
        print(f"CRITICAL ERROR: Failed to upload {entity_name} to S3: {e}")
        raise

def load_data_to_db(stints, matches, teams, players, competitions, DB_PATH=None):
    """
    Saves the data to S3 Curated zone in single files. 
    If any upload fails, the pipeline will stop.
    """
    try:
        # --- 1. Global Entities ---
        write_to_s3_parquet(teams, 'teams', pk_columns=['team_id'])
        write_to_s3_parquet(players, 'players', pk_columns=['player_id'])
        write_to_s3_parquet(competitions, 'competitions', pk_columns=['id_comp'])

        # --- 2. Matches Processing ---
        if not matches.empty:
            upcoming_matches = matches[matches['status'] == 'NO_COMENZADO'].copy()
            played_matches = matches[matches['status'] != 'NO_COMENZADO'].copy()

            # Save Upcoming Matches
            print("Saving Upcoming Matches to S3...")
            write_to_s3_parquet(upcoming_matches, 'upcoming_matches', pk_columns=['match_id'])

            # Save Played Matches (as a single file)
            if not played_matches.empty:
                print("Saving Played Matches to S3...")
                write_to_s3_parquet(played_matches, 'matches', pk_columns=['match_id'])

        # --- 3. Stints Processing (as a single file) ---
        print("Saving Stints to S3...")
        write_to_s3_parquet(stints, 'stints', pk_columns=['stint_id'])

        print("EXITO: Zona Curated actualizada correctamente en S3.")

    except Exception as e:
        # Re-raise the exception to ensure the pipeline stops
        print("PIPELINE STOPPED DUE TO S3 UPLOAD ERROR.")
        raise
