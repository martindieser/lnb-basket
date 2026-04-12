import pandas as pd
import numpy as np

class MinutesModel:
    def __init__(self):
        # Medias de referencia para los clusters
        self.means_dict = {
            -1 : 0,
            'N/A' : 0,
            'Relleno': 4.588557,
            'Suplente': 15.642886,
            'Titular': 23.635825,
            'Estrella': 31.773205
        }
        self.player_state = None   # Última foto conocida de cada jugador
        self.team_rosters = None   # Mapeo de qué jugadores pertenecen a qué equipo
        self.history_df = None     # DataFrame procesado para backtesting

    def get_cluster_id(self, avg_player):
        """Asigna el nombre del cluster basado en la distancia mínima a la media."""
        min_dist = float('inf') 
        cluster = -1
        for key in self.means_dict:
            dist = abs(self.means_dict[key] - avg_player)
            if dist < min_dist:
                min_dist = dist
                cluster = key
        return cluster

    def fit(self, boxscores, events, matches):
        """
        Procesa los datos históricos, calcula métricas móviles y guarda el estado
        actual de los jugadores y equipos para futuras predicciones.
        """
        # --- 1. Procesamiento de Minutos ---
        minutes = boxscores.groupby(['match_id', 'team_id', 'pid'])['seconds_played'].sum() / 60
        minutes = minutes.to_frame().reset_index().rename(columns={'seconds_played': 'mins', 'pid': 'player_id'})
        
        all_players_by_all_teams = events[['team_id', 'player_id']].drop_duplicates().dropna()
        matches_teams = minutes[['match_id', 'team_id']].drop_duplicates()
        
        full_scaffold = pd.merge(matches_teams, all_players_by_all_teams, on='team_id', how='left')
        
        final_df = pd.merge(
            full_scaffold, 
            minutes[['match_id', 'team_id', 'player_id', 'mins']], 
            on=['match_id', 'team_id', 'player_id'], 
            how='left'
        ).merge(matches[['match_id', 'date']], on='match_id', how='inner')

        final_df['mins'] = final_df['mins'].fillna(0)
        final_df['date'] = pd.to_datetime(final_df['date'])
        final_df = final_df.sort_values(by=['player_id', 'date'])

        # --- 2. Cálculo de métricas (Career Avg, Rolling, Inactividad) ---
        final_df['played_match'] = final_df['mins'] > 0
        final_df['has_debuted'] = final_df.groupby('player_id')['played_match'].cummax()
        
        # Filtrar solo desde el debut para promedios significativos
        played_only = final_df[final_df['played_match']].copy()
        played_only['career_avg'] = played_only.groupby('player_id')['mins'].transform(lambda x: x.expanding().mean())
        played_only['avg3_played'] = played_only.groupby('player_id')['mins'].transform(lambda x: x.rolling(window=3, min_periods=1).mean())
        played_only['played_games'] = played_only.groupby('player_id').cumcount() + 1

        final_df = pd.merge(
            final_df, 
            played_only[['match_id', 'player_id', 'career_avg', 'avg3_played', 'played_games']], 
            on=['match_id', 'player_id'], 
            how='left'
        )
        
        # Propagar valores para los partidos donde NO jugó
        final_df[['career_avg', 'avg3_played', 'played_games']] = final_df.groupby('player_id')[['career_avg', 'avg3_played', 'played_games']].ffill().fillna(0)

        # Ventana de inactividad
        final_df['is_missed'] = (final_df['mins'] == 0).astype(int)
        streak_groups = final_df.groupby('player_id')['played_match'].cumsum()
        final_df['inactivity_window'] = final_df.groupby(['player_id', streak_groups])['is_missed'].cumsum()
        
        # Asignación de Clusters
        final_df['cluster'] = final_df['career_avg'].apply(self.get_cluster_id)

        # --- 3. Generación de Columnas 'PREV' para Backtesting ---
        # Estas columnas representan lo que el modelo sabía ANTES de que se juegue el partido
        for col in ['career_avg', 'avg3_played', 'played_games', 'inactivity_window', 'cluster']:
            final_df[f'prev_{col}'] = final_df.groupby('player_id')[col].shift(1)
        
        final_df['prev_inactivity_window'] = final_df['prev_inactivity_window'].fillna(0)
        final_df['prev_played_games'] = final_df['prev_played_games'].fillna(0)

        # Guardar histórico para predict_historical
        self.history_df = final_df[final_df['has_debuted']].copy()
        
        # --- 4. Persistencia del Estado para predict_upcoming ---
        # Guardamos la última fila de cada jugador como su "Estado Actual"
        self.player_state = final_df.sort_values('date').groupby('player_id').last().reset_index()
        self.player_state = self.player_state[['player_id', 'career_avg', 'avg3_played', 'played_games', 'inactivity_window', 'cluster']]
        
        # Guardamos quién pertenece a qué equipo (último equipo registrado)
        self.team_rosters = all_players_by_all_teams.copy()

        return self

    def _base_projection_math(self, df, col_n, col_avg_recent, col_cluster_val, col_gap, k, w):
        """Lógica central: Proyección Bayesiana + Decaimiento por Inactividad."""
        cluster_means = np.array(list(self.means_dict.values()))
        cluster_keys = list(self.means_dict.keys())
        
        # 1. Determinar media del cluster según el valor de carrera pasado por parámetro
        # Si ya viene el nombre del cluster, mapeamos. Si viene el valor, buscamos el más cercano.
        if df[col_cluster_val].dtype == object:
            assigned_cluster_means = df[col_cluster_val].map(self.means_dict).fillna(self.means_dict['Relleno']).values
        else:
            avg_values = df[col_cluster_val].values
            dists = np.abs(avg_values[:, np.newaxis] - cluster_means)
            best_cluster_idx = np.argmin(dists, axis=1)
            assigned_cluster_means = cluster_means[best_cluster_idx]
        
        # 2. Factores Bayesianos
        n = df[col_n].values
        avg_recent = df[col_avg_recent].values
        f_c = k / (k + n + 1e-6)
        f_m = n / (k + n + 1e-6)
        
        mproj = (f_c * assigned_cluster_means) + (f_m * avg_recent)
        
        # 3. Decaimiento (Decay)
        gap = df[col_gap].values
        decay = 1 / (1 + np.exp(gap))
        
        return np.where(decay > (1.0/w), mproj, 0)

    def predict_historical(self, k=12.0, w=4.0):
        """Evalúa el modelo sobre partidos pasados usando columnas 'prev_'."""
        df = self.history_df.copy()
        df['expected_minutes'] = self._base_projection_math(
            df, 'prev_played_games', 'prev_avg3_played', 'prev_career_avg', 'prev_inactivity_window', k, w
        )
        return df[['match_id', 'team_id', 'player_id', 'played_match', 'expected_minutes', 'mins', 'prev_inactivity_window']].copy()

    def predict_upcoming(self, matches_df, k=12.0, w=4.0):
        """Predice minutos para un fixture de partidos futuros."""
        # Expandir Match (Home/Away) a Teams
        home = matches_df[['match_id', 'home_id']].rename(columns={'home_id': 'team_id'})
        away = matches_df[['match_id', 'away_id']].rename(columns={'away_id': 'team_id'})
        teams_in_matches = pd.concat([home, away])

        # Unir con Rosters y con el Estado actual de jugadores
        pred_df = pd.merge(teams_in_matches, self.team_rosters, on='team_id', how='inner')
        pred_df = pd.merge(pred_df, self.player_state, on='player_id', how='left')
        
        # Rellenar datos para jugadores sin historial (Rookies)
        pred_df['cluster'] = pred_df['cluster'].fillna('Relleno')
        pred_df = pred_df.fillna(0)

        # Proyectar
        pred_df['expected_minutes'] = self._base_projection_math(
            pred_df, 'played_games', 'avg3_played', 'cluster', 'inactivity_window', k, w
        )

        # Normalizar y Filtrar Top 12
        return self.get_top_rotation_minutes(pred_df)

    def get_top_rotation_minutes(self, df, top_n=12, target_mins=200):
        """Filtra los mejores 12 por equipo y ajusta la suma a target_mins."""
        # 1. Rankear jugadores por equipo
        df['rank'] = df.groupby(['match_id', 'team_id'])['expected_minutes'].rank(
            ascending=False, method='first'
        )
        
        df.loc[df['rank'] > top_n, 'expected_minutes'] = 0
        
        team_total = df.groupby(['match_id', 'team_id'])['expected_minutes'].transform('sum')
        factor = target_mins / team_total.replace(0, np.nan)
        
        df['expected_minutes'] = (df['expected_minutes'] * factor.fillna(0)).clip(upper=40)
        
        return df[['match_id', 'team_id', 'player_id', 'expected_minutes']].copy()