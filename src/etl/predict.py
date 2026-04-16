import pandas as pd
import logging
import json
import os
from src.stats.elo import calculate_elo_ratings, train_prediction_model, predict_upcoming
from src.etl.load import write_to_s3_parquet
from src.config import S3_BUCKET_NAME, S3_CURATED_PREFIX

logger = logging.getLogger(__name__)

def generate_predictions():
    """
    Generates predictions using the Elo model and saves them to S3 in a generic format.
    Also generates a leaderboard/standings file.
    """
    if not S3_BUCKET_NAME:
        logger.error("S3_BUCKET_NAME not configured. Skipping prediction generation.")
        return

    # 1. Load data from S3 Curated
    matches_path = f"s3://{S3_BUCKET_NAME}/{S3_CURATED_PREFIX}/matches/data.parquet"
    upcoming_path = f"s3://{S3_BUCKET_NAME}/{S3_CURATED_PREFIX}/upcoming_matches/data.parquet"
    teams_path = f"s3://{S3_BUCKET_NAME}/{S3_CURATED_PREFIX}/teams/data.parquet"

    try:
        df_matches = pd.read_parquet(matches_path, engine='pyarrow').sort_values('date')
        df_upcoming = pd.read_parquet(upcoming_path, engine='pyarrow')
        df_teams = pd.read_parquet(teams_path, engine='pyarrow')
    except Exception as e:
        logger.error(f"Error loading data from S3 for predictions: {e}")
        return

    if df_matches.empty or df_upcoming.empty:
        logger.warning("Matches or Upcoming matches data is empty. Skipping.")
        return

    # 2. Run Elo Model
    logger.info("Calculating Elo ratings...")
    elo_ratings, elo_history = calculate_elo_ratings(df_matches)
    
    logger.info("Training prediction model...")
    model = train_prediction_model(elo_history)
    
    logger.info("Generating upcoming predictions...")
    preds = predict_upcoming(df_upcoming, elo_ratings, model)

    # 3. Format Generic Predictions
    # Columns: match_id, model_name, pred_diff_pts, pred_winner, metadata (JSON)
    generic_preds = pd.DataFrame()
    generic_preds['match_id'] = preds['match_id']
    generic_preds['model_name'] = 'elo_base'
    generic_preds['pred_diff_pts'] = preds['pred_diff_pts']
    generic_preds['pred_winner'] = preds['pred_winner']
    
    # Store elo_home and elo_away in metadata
    generic_preds['metadata'] = preds.apply(
        lambda x: json.dumps({
            'elo_home': round(x['elo_home'], 1),
            'elo_away': round(x['elo_away'], 1),
            'elo_diff': round(x['elo_diff'], 1)
        }), axis=1
    )

    # 4. Format Leaderboard
    team_names = df_teams.set_index('team_id')['team_name'].to_dict()
    leaderboard_data = [
        {"team_id": tid, "team_name": team_names.get(tid, tid), "elo": round(elo, 1)}
        for tid, elo in elo_ratings.items()
    ]
    df_leaderboard = pd.DataFrame(leaderboard_data).sort_values("elo", ascending=False).reset_index(drop=True)

    # 5. Save to S3
    logger.info("Saving predictions and leaderboard to S3...")
    write_to_s3_parquet(generic_preds, 'predictions', pk_columns=['match_id', 'model_name'], upsert=False)
    write_to_s3_parquet(df_leaderboard, 'leaderboard', pk_columns=['team_id'], upsert=False)
    
    logger.info("Prediction generation completed successfully.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    generate_predictions()
