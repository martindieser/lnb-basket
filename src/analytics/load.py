from src.config import get_logger
from src.utils import write_to_s3_parquet

logger = get_logger()

# Prefix for the Gold/Analytics zone
S3_ANALYTICS_PREFIX = "analytics"

def load_gold_data(gold_data):
    """
    Saves the Gold/Analytics tables to S3.
    """
    stats = {}
    try:
        # Save Facts (Upsert)
        stats['fact_player_stints'] = write_to_s3_parquet(
            gold_data['fact_player_stints'], 
            S3_ANALYTICS_PREFIX,
            'fact_player_stints', 
            pk_columns=['stint_id', 'match_id', 'team_id', 'player_id'], 
            upsert=True
        )
        
       
        # Save Dimensions (Upsert)
        stats['dim_stint'] = write_to_s3_parquet(
            gold_data['dim_stint'], 
            S3_ANALYTICS_PREFIX,
            'dim_stint', 
            pk_columns=['stint_id', 'match_id'], 
            upsert=True
        )
        
        stats['dim_match'] = write_to_s3_parquet(
            gold_data['dim_match'], 
            S3_ANALYTICS_PREFIX,
            'dim_match', 
            pk_columns=['match_id'], 
            upsert=True
        )
        
        stats['dim_player'] = write_to_s3_parquet(
            gold_data['dim_player'], 
            S3_ANALYTICS_PREFIX,
            'dim_player', 
            pk_columns=['player_id'], 
            upsert=True
        )
        
        stats['dim_team'] = write_to_s3_parquet(
            gold_data['dim_team'], 
            S3_ANALYTICS_PREFIX,
            'dim_team', 
            pk_columns=['team_id'], 
            upsert=True
        )
        
        stats['dim_competition'] = write_to_s3_parquet(
            gold_data['dim_competition'], 
            S3_ANALYTICS_PREFIX,
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
