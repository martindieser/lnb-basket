import json
import boto3
from typing import Dict
from src.config import S3_BUCKET_NAME, S3_RAW_PREFIX, get_logger

logger = get_logger()

# S3 key for the unified player details file
PLAYER_DETAILS_S3_KEY = f"{S3_RAW_PREFIX}/player_details/proballers.json"

def load_player_details(raw_data: Dict[str, Dict]) -> None:
    """
    Saves the complete player details dictionary to a single JSON file in S3 (proballers.json),
    strictly overwriting any existing file.
    """
    if not S3_BUCKET_NAME:
        logger.error("S3_BUCKET_NAME environment variable is not set. S3 upload skipped.")
        return

    s3_client = boto3.client('s3')
    
    try:
        logger.info(f"Uploading and overwriting proballers.json in S3 at {PLAYER_DETAILS_S3_KEY} with {len(raw_data)} records...")
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=PLAYER_DETAILS_S3_KEY,
            Body=json.dumps(raw_data, ensure_ascii=False, indent=4),
            ContentType='application/json'
        )
        logger.info("Successfully uploaded and overwritten proballers.json in S3.")
    except Exception as e:
        logger.error(f"Failed to upload unified player details to S3: {e}")
        raise
