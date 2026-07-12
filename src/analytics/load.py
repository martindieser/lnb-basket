import pandas as pd
from src.config import S3_BUCKET_NAME, get_logger

logger = get_logger()

# Prefix for the Gold/Analytics zone
S3_ANALYTICS_PREFIX = "analytics"

def write_to_s3_parquet(df, entity_name, pk_columns=None, upsert=True):
    """
    Writes a DataFrame to S3 as a single Parquet file in the Analytics zone.
    If upsert=True, it merges with existing data. If False, it overwrites.
    Returns: Final count of records saved.
    """
    if not S3_BUCKET_NAME or df.empty:
        logger.warning(f"Skipping upload for {entity_name}: S3_BUCKET_NAME is not set or DataFrame is empty.")
        return 0

    s3_path = f"s3://{S3_BUCKET_NAME}/{S3_ANALYTICS_PREFIX}/{entity_name}/data.parquet"
    
    # 1. Attempt to load existing data for Upsert
    if upsert:
        try:
            existing_df = pd.read_parquet(s3_path, engine='pyarrow')
            df = pd.concat([existing_df, df], ignore_index=True)
            logger.info(f"Loaded existing data for {entity_name} from S3 for upsert.")
        except Exception:
            # File doesn't exist, proceed with current df
            logger.info(f"No existing data found for {entity_name} in S3, creating new file.")
            pass

    # 2. Cleanup of duplicates before writing
    if pk_columns:
        df = df.drop_duplicates(subset=pk_columns, keep='last')
        
    try:
        df.to_parquet(s3_path, index=False, engine='pyarrow')
        logger.info(f"Successfully uploaded {entity_name} to {s3_path} ({len(df)} records).")
        return len(df)
    except Exception as e:
        logger.error(f"CRITICAL ERROR: Failed to upload {entity_name} to S3: {e}")
        raise

def load_gold_data(gold_data):
    """
    Saves the Gold/Analytics tables to S3.
    """
    stats = {}
    try:
        # Save Facts (Upsert)
        stats['fact_player_stints'] = write_to_s3_parquet(
            gold_data['fact_player_stints'], 
            'fact_player_stints', 
            pk_columns=['stint_id', 'match_id', 'team_id', 'player_id'], 
            upsert=True
        )
       
        # Save Dimensions (Upsert)
        stats['dim_stint'] = write_to_s3_parquet(
            gold_data['dim_stint'], 
            'dim_stint', 
            pk_columns=['stint_id', 'match_id'], 
            upsert=True
        )
        
        stats['dim_match'] = write_to_s3_parquet(
            gold_data['dim_match'], 
            'dim_match', 
            pk_columns=['match_id'], 
            upsert=True
        )
        
        stats['dim_player'] = write_to_s3_parquet(
            gold_data['dim_player'], 
            'dim_player', 
            pk_columns=['player_id'], 
            upsert=True
        )
        
        stats['dim_team'] = write_to_s3_parquet(
            gold_data['dim_team'], 
            'dim_team', 
            pk_columns=['team_id'], 
            upsert=True
        )
        
        stats['dim_competition'] = write_to_s3_parquet(
            gold_data['dim_competition'], 
            'dim_competition', 
            pk_columns=['id_comp'], 
            upsert=True
        )
        
        # --- Final Summary ---
        logger.info("="*40)
        logger.info("S3 ANALYTICS ZONE UPDATE SUMMARY")
        logger.info("="*40)
        for entity, count in stats.items():
            logger.info(f"- {entity:<22}: {count:>6} records [Upsert (Total)]")
        logger.info("="*40)
        logger.info("SUCCESS: Analytics layer updated successfully in S3.")
        
        return stats

    except Exception as e:
        logger.error(f"PIPELINE STOPPED DUE TO S3 UPLOAD ERROR IN GOLD: {e}")
        raise
