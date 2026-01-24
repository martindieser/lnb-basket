import os
import json
import logging

import os
import json
import logging
from collections import defaultdict

def extract_dirs(base_directory: str) -> dict:
    """
    Scans subdirectories within base_directory and organizes data by competition and match_id.
    
    Expected folder structure:
    - agg_by_player_{competition}_basketball/
    - agg_by_team_{competition}_basketball/
    - pbp_{competition}_basketball/
    
    Returns: {competition: {match_id: {'agg_player': data, 'agg_team': data, 'pbp': data}}}
    """
    result = defaultdict(lambda: defaultdict(dict))
    
    if not os.path.exists(base_directory):
        logging.error(f"Base directory does not exist: {base_directory}")
        return {}
    
    # Iterate through folders in the base directory
    for folder_name in os.listdir(base_directory):
        folder_path = os.path.join(base_directory, folder_name)
        
        # Only process if it's a directory
        if not os.path.isdir(folder_path):
            continue
        
        # Parse folder name to extract competition and data type
        # Expected format: {type}_{competition}_basketball
        if folder_name.startswith('agg_by_player_'):
            data_type = 'agg_player'
            competition = folder_name.replace('agg_by_player_', '').replace('_basketball', '')
        elif folder_name.startswith('agg_by_team_'):
            data_type = 'agg_team'
            competition = folder_name.replace('agg_by_team_', '').replace('_basketball', '')
        elif folder_name.startswith('pbp_'):
            data_type = 'pbp'
            competition = folder_name.replace('pbp_', '').replace('_basketball', '')
        else:
            logging.warning(f"Unknown folder format: {folder_name}")
            continue
        
        # Look for JSON files inside the folder
        files = [f for f in os.listdir(folder_path) if f.endswith('.json')]
        
        for file_name in files:
            full_path = os.path.join(folder_path, file_name)
            
            # Extract match_id from filename (assuming format like "12345.json")
            match_id = file_name.replace('.json', '')
            
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    result[competition][match_id][data_type] = data
            except Exception as e:
                logging.error(f"Error loading {file_name} in {folder_name}: {e}")
    
    # Convert defaultdict to regular dict for cleaner output
    return {comp: dict(matches) for comp, matches in result.items()}