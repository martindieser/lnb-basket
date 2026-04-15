import pandas as pd
import numpy as np
import statsmodels.api as sm

def calculate_elo_ratings(df_matches, k_factor=20, home_advantage=100):
    """
    Calculates Elo ratings for teams based on historical matches.
    Assumes df_matches is sorted by date.
    """
    elo_ratings = {}  # team_id -> current elo

    def get_elo(team_id, default=1500):
        return elo_ratings.get(team_id, default)

    def expected_score(elo_a, elo_b):
        return 1 / (1 + 10 ** ((elo_b - elo_a) / 400))

    elo_history = []

    for _, row in df_matches.iterrows():
        h_id = row['home_id']
        a_id = row['away_id']
        h_pts = row['home_pts']
        a_pts = row['away_pts']

        # ELO before match (with home advantage for prediction logic)
        elo_h_pre = get_elo(h_id)
        elo_a_pre = get_elo(a_id)
        
        # Store ratings before the match
        elo_history.append({
            'match_id': row['match_id'],
            'elo_home_pre': elo_h_pre,
            'elo_away_pre': elo_a_pre,
            'elo_diff': elo_h_pre + home_advantage - elo_a_pre,
            'diff_pts': h_pts - a_pts
        })

        # Outcome: 1 for home win, 0.5 for draw (not usual in basket but good to handle), 0 for away win
        if h_pts > a_pts:
            actual_h = 1
        elif h_pts < a_pts:
            actual_h = 0
        else:
            actual_h = 0.5

        # Expected score for home team (including advantage)
        exp_h = expected_score(elo_h_pre + home_advantage, elo_a_pre)

        # Update ELOs
        new_elo_h = elo_h_pre + k_factor * (actual_h - exp_h)
        new_elo_a = elo_a_pre + k_factor * ((1 - actual_h) - (1 - exp_h))

        elo_ratings[h_id] = new_elo_h
        elo_ratings[a_id] = new_elo_a

    return elo_ratings, pd.DataFrame(elo_history)

def train_prediction_model(df_history):
    """
    Trains a simple OLS model to predict diff_pts based on elo_diff.
    """
    if df_history.empty:
        return None
    
    X = df_history[['elo_diff']]
    y = df_history['diff_pts']
    
    X = sm.add_constant(X)
    model = sm.OLS(y, X).fit()
    return model

def predict_upcoming(df_upcoming, elo_ratings, model, home_advantage=100):
    """
    Predicts point differences for upcoming matches.
    """
    predictions = []
    
    for _, row in df_upcoming.iterrows():
        h_id = row['home_id']
        a_id = row['away_id']
        
        elo_h = elo_ratings.get(h_id, 1500)
        elo_a = elo_ratings.get(a_id, 1500)
        
        elo_diff = elo_h + home_advantage - elo_a
        
        if model:
            # Predict using model: diff_pts = const + coef * elo_diff
            # We ensure columns match the order model.params expects
            pred_input = pd.DataFrame({'const': [1.0], 'elo_diff': [elo_diff]})
            pred_input = pred_input[model.params.index]
            pred_diff = model.predict(pred_input)[0]
        else:
            # Fallback to notebook coefficients if no model could be trained
            pred_diff = 4.4931 + 0.0526 * elo_diff
            
        predictions.append({
            'match_id': row['match_id'],
            'home_id': h_id,
            'away_id': a_id,
            'elo_home': elo_h,
            'elo_away': elo_a,
            'elo_diff': elo_diff,
            'pred_diff_pts': pred_diff,
            'pred_winner': 'LOCAL' if pred_diff > 0 else 'VISITANTE'
        })
        
    return pd.DataFrame(predictions)
