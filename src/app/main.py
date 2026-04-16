import streamlit as st
import duckdb
import pandas as pd
import os
import json

# Configure page
st.set_page_config(page_title="Predicciones LNB", layout="wide")
st.title("LNB Basket: Predicciones")

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
        return None, None, None, None

    conn = get_duckdb_conn()
    
    try:
        # Define S3 paths
        upcoming_path = f"s3://{S3_BUCKET}/{S3_CURATED}/upcoming_matches/data.parquet"
        teams_path = f"s3://{S3_BUCKET}/{S3_CURATED}/teams/data.parquet"
        predictions_path = f"s3://{S3_BUCKET}/{S3_CURATED}/predictions/data.parquet"
        leaderboard_path = f"s3://{S3_BUCKET}/{S3_CURATED}/leaderboard/data.parquet"
        
        # Load dataframes using DuckDB
        df_upcoming = conn.execute(f"SELECT * FROM read_parquet('{upcoming_path}')").df()
        df_teams = conn.execute(f"SELECT * FROM read_parquet('{teams_path}')").df()
        df_preds = conn.execute(f"SELECT * FROM read_parquet('{predictions_path}')").df()
        df_leaderboard = conn.execute(f"SELECT * FROM read_parquet('{leaderboard_path}')").df()
        
        return df_upcoming, df_teams, df_preds, df_leaderboard
    except Exception as e:
        st.error(f"Error cargando datos de S3: {e}")
        return None, None, None, None

df_upcoming, df_teams, df_preds, df_leaderboard = load_data()

if df_preds is not None and df_teams is not None:
    # 1. Sidebar: Leaderboard
    st.sidebar.header("Ranking Elo (Actualizado)")
    team_names = df_teams.set_index('team_id')['team_name'].to_dict()
    
    display_leaderboard = df_leaderboard.copy()
    display_leaderboard = display_leaderboard.rename(columns={
        'team_name': 'Equipo',
        'elo': 'Elo'
    })
    st.sidebar.table(display_leaderboard[['Equipo', 'Elo']])
    
    # 2. Main Dashboard: Upcoming Predictions
    st.header("Próximos Partidos y Predicciones")
    
    # Model Selection (Future proofing)
    available_models = df_preds['model_name'].unique().tolist()
    selected_model = st.selectbox("Seleccionar Modelo de Predicción", available_models, index=0)
    
    filtered_preds = df_preds[df_preds['model_name'] == selected_model].copy()
    
    if not filtered_preds.empty:
        # Join with team names and upcoming info
        upcoming_info = df_upcoming[['match_id', 'date', 'home_id', 'away_id']]
        display_df = filtered_preds.merge(upcoming_info, on='match_id')
        
        display_df['Local'] = display_df['home_id'].map(team_names)
        display_df['Visitante'] = display_df['away_id'].map(team_names)
        
        # Extract metadata if available
        if 'metadata' in display_df.columns:
            meta_df = display_df['metadata'].apply(lambda x: json.loads(x) if isinstance(x, str) else x).apply(pd.Series)
            display_df = pd.concat([display_df, meta_df], axis=1)
        
        # Prepare final columns for display
        cols_to_show = ['date', 'Local', 'Visitante']
        
        # Model specific columns from metadata
        if 'elo_home' in display_df.columns and 'elo_away' in display_df.columns:
            cols_to_show += ['elo_home', 'elo_away']
            
        cols_to_show += ['pred_diff_pts', 'pred_winner']
        
        final_display = display_df[cols_to_show].copy()
        
        # Rename for UI
        rename_dict = {
            'date': 'Fecha',
            'pred_diff_pts': 'Dif. Puntos Pred.',
            'pred_winner': 'Ganador Pred.',
            'elo_home': 'Elo Local',
            'elo_away': 'Elo Visitante'
        }
        final_display = final_display.rename(columns=rename_dict)
        
        # Formatting
        if 'Elo Local' in final_display.columns:
            final_display['Elo Local'] = final_display['Elo Local'].round(1)
        if 'Elo Visitante' in final_display.columns:
            final_display['Elo Visitante'] = final_display['Elo Visitante'].round(1)
        
        final_display['Dif. Puntos Pred.'] = final_display['Dif. Puntos Pred.'].round(2)
        
        # Sort by date
        final_display = final_display.sort_values('Fecha')
        
        st.dataframe(final_display, use_container_width=True)
        
        if selected_model == 'elo_base':
            st.info("Interpretación: `Dif. Puntos Pred.` > 0 favorece al equipo LOCAL. El Elo incluye una ventaja de local de 100 puntos.")
    else:
        st.write("No se encontraron predicciones próximas para el modelo seleccionado.")
            
else:
    st.info("Esperando datos de S3 (predicciones y leaderboard)...")
