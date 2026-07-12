import os
import json
import logging
import boto3
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from src.config import S3_BUCKET_NAME, S3_RAW_PREFIX

# Path for the state registry in S3
S3_STATE_PREFIX = f"{S3_RAW_PREFIX}/_state"
REGISTRY_KEY = f"{S3_STATE_PREFIX}/processed_keys.json"

def extract_dirs() -> tuple:
    """
    Scans S3 and organizes data by competition and match_id.
    Only returns data for files NOT already processed.
    
    Returns: (dict, list_of_new_keys)
    """
    if not S3_BUCKET_NAME:
        logging.error("S3_BUCKET_NAME environment variable is not set. S3 is mandatory.")
        return {}, []
        
    return extract_from_s3()

def _download_and_parse_s3(s3_client, key):
    """
    Worker function for ThreadPoolExecutor.
    """
    try:
        resp = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=key)
        data = json.loads(resp['Body'].read().decode('utf-8'))
        return key, data
    except Exception as e:
        logging.error(f"Error loading S3 key {key}: {e}")
        return key, None

def get_processed_registry(s3_client):
    """
    Reads the list of processed S3 keys from the registry file.
    """
    try:
        resp = s3_client.get_object(Bucket=S3_BUCKET_NAME, Key=REGISTRY_KEY)
        return set(json.loads(resp['Body'].read().decode('utf-8')))
    except s3_client.exceptions.NoSuchKey:
        return set()
    except Exception as e:
        logging.error(f"Error reading registry: {e}")
        return set()

def update_processed_registry(s3_client, new_keys, existing_registry=None):
    """
    Saves the updated list of processed S3 keys back to S3.
    """
    if not new_keys:
        return
        
    registry = existing_registry or get_processed_registry(s3_client)
    updated_registry = list(registry.union(new_keys))
    
    try:
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=REGISTRY_KEY,
            Body=json.dumps(updated_registry),
            ContentType='application/json'
        )
        logging.info(f"Updated registry with {len(new_keys)} new keys.")
    except Exception as e:
        logging.error(f"Error updating registry: {e}")

def extract_from_s3() -> tuple:
    """
    Lists all objects in S3 and downloads only those NOT in the registry.
    Uses ThreadPoolExecutor for concurrent downloads.
    """
    s3_client = boto3.client('s3')
    result = defaultdict(lambda: defaultdict(dict))
    
    # 1. Load registry
    processed_keys = get_processed_registry(s3_client)
    keys_to_download = []
    
    try:
        # 2. List all JSON files and filter
        paginator = s3_client.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=f"{S3_RAW_PREFIX}/"):
            if 'Contents' not in page:
                continue
                
            for obj in page['Contents']:
                key = obj['Key']
                # Skip registry, non-json files, and the profiles folder
                if not key.endswith('.json') or key == REGISTRY_KEY or f"/{S3_RAW_PREFIX}/profiles/" in f"/{key}":
                    continue
                
                if key in processed_keys:
                    continue
                
                keys_to_download.append(key)
        
        if not keys_to_download:
            logging.info("No new files found in S3 raw zone.")
            return {}, []

        logging.info(f"Found {len(keys_to_download)} new files. Starting concurrent download...")

        # 3. Download concurrently
        new_data_map = {}
        with ThreadPoolExecutor(max_workers=7) as executor:
            futures = [executor.submit(_download_and_parse_s3, s3_client, key) for key in keys_to_download]
            for future in futures:
                key, data = future.result()
                if data:
                    new_data_map[key] = data

        # 4. Organize data by competition/match_id
        for key, data in new_data_map.items():
            # key format: raw/{folder_name}/{file_name}.json
            parts = key.split('/')
            if len(parts) < 3:
                continue
            
            folder_name = parts[1]
            file_name = parts[2]
            match_id = file_name.replace('.json', '')
            
            data_type, competition = _parse_folder_name(folder_name)
            if data_type and competition:
                result[competition][match_id][data_type] = data
                
    except Exception as e:
        logging.error(f"Error during S3 extraction: {e}")
        
    organized_result = {comp: dict(matches) for comp, matches in result.items()}
    # Exclude 'upcoming' folder keys from registry tracking
    actual_new_keys = [k for k in new_data_map.keys() if '/upcoming/' not in k]
    
    return organized_result, actual_new_keys

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