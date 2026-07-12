import pandas as pd
from src.config import S3_BUCKET_NAME, S3_CURATED_PREFIX, get_logger

logger = get_logger()

def extract_silver_data():
    """
    Reads Silver tables from S3 Parquet.
    Returns:
        dict: A dictionary of DataFrames for matches, pbps, players, teams, and competitions.
    """
    if not S3_BUCKET_NAME:
        raise ValueError("S3_BUCKET_NAME is not set in the environment.")
        
    logger.info("Extracting Silver data from S3...")
    
    # Read matches
    matches_path = f"s3://{S3_BUCKET_NAME}/{S3_CURATED_PREFIX}/matches/data.parquet"
    logger.info(f"Reading matches from {matches_path}")
    matches = pd.read_parquet(matches_path, engine='pyarrow')
    
    # Read pbps
    pbps_path = f"s3://{S3_BUCKET_NAME}/{S3_CURATED_PREFIX}/pbps/data.parquet"
    logger.info(f"Reading pbps from {pbps_path}")
    pbps = pd.read_parquet(pbps_path, engine='pyarrow')
    
    # Read players
    players_path = f"s3://{S3_BUCKET_NAME}/{S3_CURATED_PREFIX}/players/data.parquet"
    logger.info(f"Reading players from {players_path}")
    players = pd.read_parquet(players_path, engine='pyarrow')
    
    # Read teams
    teams_path = f"s3://{S3_BUCKET_NAME}/{S3_CURATED_PREFIX}/teams/data.parquet"
    logger.info(f"Reading teams from {teams_path}")
    teams = pd.read_parquet(teams_path, engine='pyarrow')
    
    # Read competitions
    comp_path = f"s3://{S3_BUCKET_NAME}/{S3_CURATED_PREFIX}/competitions/data.parquet"
    logger.info(f"Reading competitions from {comp_path}")
    competitions = pd.read_parquet(comp_path, engine='pyarrow')
    
    return {
        'matches': matches,
        'pbps': pbps,
        'players': players,
        'teams': teams,
        'competitions': competitions
    }
