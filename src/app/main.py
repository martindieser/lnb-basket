import streamlit as st
import duckdb
import pandas as pd
import os
from src.stats.elo import calculate_elo_ratings, train_prediction_model, predict_upcoming

# Configure page
st.set_page_config(page_title="Predicciones LNB", layout="wide")
st.title("LNB Basket: Predicciones y Ratings Elo")

# S3 Configuration from environment
S3_BUCKET = os.getenv("S3_BUCKET_NAME")
S3_CURATED = os.getenv("S3_CURATED_PREFIX", "curated")

def get_duckdb_conn():
    conn = duckdb.connect(database=':memory:')
    conn.execute("INSTALL httpfs;")
    conn.execute("LOAD httpfs;")
    
    # Optional: Configure S3 if credentials are provided in env
    aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    aws_region = os.getenv("AWS_REGION", "us-east-1")
    
    if aws_access_key and aws_secret_key:
        conn.execute(f"SET s3_access_key_id='{aws_access_key}';")
        conn.execute(f"SET s3_secret_access_key='{aws_secret_key}';")
        conn.execute(f"SET s3_region='{aws_region}';")
    
    return conn

@st.cache_data(ttl=3600)
def load_data():
    if not S3_BUCKET:
        st.error("S3_BUCKET_NAME no configurado en variables de entorno.")
        return None, None, None

    conn = get_duckdb_conn()
    
    try:
        # Define S3 paths
        matches_path = f"s3://{S3_BUCKET}/{S3_CURATED}/matches/data.parquet"
        upcoming_path = f"s3://{S3_BUCKET}/{S3_CURATED}/upcoming_matches/data.parquet"
        teams_path = f"s3://{S3_BUCKET}/{S3_CURATED}/teams/data.parquet"
        
        # Load dataframes using DuckDB
        df_matches = conn.execute(f"SELECT * FROM read_parquet('{matches_path}') ORDER BY date").df()
        df_upcoming = conn.execute(f"SELECT * FROM read_parquet('{upcoming_path}')").df()
        df_teams = conn.execute(f"SELECT * FROM read_parquet('{teams_path}')").df()
        
        return df_matches, df_upcoming, df_teams
    except Exception as e:
        st.error(f"Error cargando datos de S3: {e}")
        return None, None, None

df_matches, df_upcoming, df_teams = load_data()

if df_matches is not None and df_teams is not None:
    # 1. Calculate Elo ratings
    elo_ratings, elo_history = calculate_elo_ratings(df_matches)
    model = train_prediction_model(elo_history)
    
    # 2. Sidebar: Leaderboard
    st.sidebar.header("Ranking Elo")
    team_names = df_teams.set_index('team_id')['team_name'].to_dict()
    
    leaderboard_data = [
        {"Equipo": team_names.get(tid, tid), "Elo": round(elo, 1)}
        for tid, elo in elo_ratings.items()
    ]
    df_leaderboard = pd.DataFrame(leaderboard_data).sort_values("Elo", ascending=False).reset_index(drop=True)
    st.sidebar.table(df_leaderboard)
    
    # 3. Main Dashboard: Upcoming Predictions
    st.header("Próximos Partidos y Predicciones")
    
    if df_upcoming is not None and not df_upcoming.empty:
        preds = predict_upcoming(df_upcoming, elo_ratings, model)
        
        # Join with team names and prepare display
        display_df = preds.copy()
        display_df['Local'] = display_df['home_id'].map(team_names)
        display_df['Visitante'] = display_df['away_id'].map(team_names)
        
        # Add date and status from original upcoming_matches
        upcoming_info = df_upcoming[['match_id', 'date', 'status']]
        display_df = display_df.merge(upcoming_info, on='match_id')
        
        # Final columns for display
        final_display = display_df[[
            'date', 'Local', 'Visitante', 'elo_home', 'elo_away', 
            'pred_diff_pts', 'pred_winner'
        ]].copy()
        
        final_display = final_display.rename(columns={
            'date': 'Fecha',
            'elo_home': 'Elo Local',
            'elo_away': 'Elo Visitante',
            'pred_diff_pts': 'Dif. Puntos Pred.',
            'pred_winner': 'Ganador Pred.'
        })
        
        final_display['Elo Local'] = final_display['Elo Local'].round(1)
        final_display['Elo Visitante'] = final_display['Elo Visitante'].round(1)
        final_display['Dif. Puntos Pred.'] = final_display['Dif. Puntos Pred.'].round(2)
        
        # Sort by date
        final_display = final_display.sort_values('Fecha')
        
        st.dataframe(final_display, use_container_width=True)
        
        st.info("Interpretación: `Dif. Puntos Pred.` > 0 favorece al equipo LOCAL. El Elo incluye una ventaja de local de 100 puntos.")
    else:
        st.write("No se encontraron partidos próximos.")
    
    # 4. Optional: Model Summary
    if st.checkbox("Mostrar detalles del modelo (OLS)"):
        if model:
            st.text(model.summary())
        else:
            st.write("Modelo no entrenado (usando coeficientes por defecto).")
            
else:
    st.info("Esperando datos de S3...")
