import os
import json
import logging
import boto3
from collections import defaultdict
from src.config import S3_BUCKET_NAME, S3_RAW_PREFIX

def extract_dirs(base_directory: str = None) -> dict:
    """
    Scans S3 and organizes data by competition and match_id.
    
    S3_BUCKET_NAME must be configured.
    """
    if not S3_BUCKET_NAME:
        logging.error("S3_BUCKET_NAME environment variable is not set. S3 is mandatory.")
        return {}
        
    return extract_from_s3()

def extract_from_s3() -> dict:
    """
    Lists and reads objects from S3 bucket under the raw prefix.
    """
    s3_client = boto3.client('s3')
    result = defaultdict(lambda: defaultdict(dict))
    
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=f"{S3_RAW_PREFIX}/"):
            if 'Contents' not in page:
                continue
                
            for obj in page['Contents']:
                key = obj['Key']
                if not key.endswith('.json'):
                    continue
                
                # key format: raw/{folder_name}/{file_name}.json
                parts = key.split('/')
                if len(parts) < 3:
                    continue
                
                folder_name = parts[1]
                file_name = parts[2]
                match_id = file_name.replace('.json', '')
                
                data_type, competition = _parse_folder_name(folder_name)
                if not data_type:
                    continue
                
                try:
                    resp = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=key)
                    data = json.loads(resp['Body'].read().decode('utf-8'))
                    result[competition][match_id][data_type] = data
                except Exception as e:
                    logging.error(f"Error loading S3 key {key}: {e}")
                    
    except Exception as e:
        logging.error(f"Error connecting to S3: {e}")
        
    return {comp: dict(matches) for comp, matches in result.items()}

def _parse_folder_name(folder_name: str):
    """
    Helper to extract data_type and competition from folder name.
    """
    if folder_name.startswith('agg_by_player_'):
        return 'agg_player', folder_name.replace('agg_by_player_', '').replace('_basketball', '')
    elif folder_name.startswith('agg_by_team_'):
        return 'agg_team', folder_name.replace('agg_by_team_', '').replace('_basketball', '')
    elif folder_name.startswith('pbp_'):
        return 'pbp', folder_name.replace('pbp_', '').replace('_basketball', '')
    elif folder_name == 'upcoming':
        return 'pbp', 'upcoming'
    return None, None