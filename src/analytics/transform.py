import pandas as pd
from src.config import get_logger
from collections import defaultdict
from tqdm import tqdm

logger = get_logger()





class Stint:
    def __init__(self, match_id, stint_id, start, nperiod, h_lineup, a_lineup, home_id, away_id, cols):
        self.match_id = match_id
        self.stint_id = stint_id
        self.start = start
        self.end = '00:00:00.0'
        self.nperiod = nperiod
        self.home_lineup = h_lineup.copy()
        self.away_lineup = a_lineup.copy()
        self.home_id = home_id
        self.away_id = away_id
        self.home_stats = {c: 0 for c in cols}
        self.away_stats = {c: 0 for c in cols}
        self.cols = cols
        # Seed: todo jugador en cancha arranca en 0, aunque no genere eventos
        self.player_stats = {
            pid: {c: 0 for c in cols} for pid in (self.home_lineup | self.away_lineup)
        }


    def add_stat(self, team_id, col, val, pid):
        stats = self.home_stats if team_id == self.home_id else self.away_stats
        stats[col] += val
        if pid not in self.player_stats:
            self.player_stats[pid] = {c: 0 for c in self.cols}
        self.player_stats[pid][col] += val

    def close(self, etime, h_lineup=None, a_lineup=None):
        self.end = etime
        if h_lineup is not None:
            self.home_lineup = h_lineup.copy()
        if a_lineup is not None:
            self.away_lineup = a_lineup.copy()


    def _to_sec(self, clk):
        hh, mm, ss = clk.split(':')
        return int(mm) * 60 + float(ss)

    def to_dict(self):
        d = {
            'stint_id': self.stint_id, "match_id" : self.match_id, 'nperiod': self.nperiod,
            'start_clk': self.start, 'end_clk': self.end,
            'duration_sec': self._to_sec(self.start) - self._to_sec(self.end),
        }
        return d

    def to_player_rows(self):
        """Formato long: una fila por (stint, player)."""
        rows = []
        for pid in self.home_lineup:
            row = {'stint_id': self.stint_id, "match_id" : self.match_id,
                    'player_id': pid, 'team_id': self.home_id}
                   
            row.update(self.player_stats.get(pid, {c: 0 for c in self.cols}))
            rows.append(row)
        for pid in self.away_lineup:
            row = {'stint_id': self.stint_id, "match_id" : self.match_id,
                    'player_id': pid, 'team_id': self.away_id}
 
            row.update(self.player_stats.get(pid, {c: 0 for c in self.cols}))
            rows.append(row)
        return rows




class StintParser:
    # Definimos las columnas base
    COLS = (
        'pts', 'pf', 'fg3m', 'fg3a', 'fg2m', 'fg2a', 'fg1m', 'fg1a',
        'fta', 'ftm', 'tov', 'stl', 'orb', 'drb', 'ast', 'blk', 'ba', 
        'tout', 'tech', 'flg', 'ftrips'
    )

    # Definimos eventos a ignorar
    IGNORE_EVENTS = {
        'FALTA-RECIBIDA', 
        '1-TIRO-LIBRE', 
        'FLECHA-ALTERNANCIA-LOCAL', 
        'FLECHA-ALTERNANCIA-VISITANTE'
    }

    # Mapeo de Evento -> Lista de (Columna, Valor)
    # Esto es mucho más rápido que iterar listas de tuplas
    STAT_MAPPING = {
        'PERDIDA':                  [('tov', 1)],
        'REBOTE-DEFENSIVO':         [('drb', 1)],
        'REBOTE-OFENSIVO':          [('orb', 1)],
        
        # Tiros fallados
        'TIRO1-FALLADO':            [('fg1m', 1), ('fta', 1)], # Revisa si fg1m acá es intento o metido en tu lógica original parecía intento
        'TIRO3-FALLADO':            [('fg3a', 1)],
        'TIRO2-FALLADO':            [('fg2a', 1)],

        # Canastas (Suman Puntos + Metidos + Intentados implícitos si se requiere)
        'CANASTA-3P':               [('pts', 3), ('fg3m', 1), ('fg3a', 1)],
        'CANASTA-2P':               [('pts', 2), ('fg2m', 1), ('fg2a', 1)],
        'CANASTA-1P':               [('pts', 1), ('fg1m', 1), ('ftm', 1), ('fta', 1)], 

        'RECUPERACION':             [('stl', 1)],
        'TIEMPO-MUERTO-SOLICITADO': [('tout', 1)],
        
        # Tiros libres trips
        '3-TIROS-LIBRES':           [('ftrips', 1)],
        '2-TIROS-LIBRES':           [('ftrips', 1)],

        # Faltas
        'TANTIDEPORTIVA':           [('flg', 1), ('pf', 1)],
        'TECNICA':                  [('tech', 1), ('pf', 1)],
        'TBANQUILLO-C':             [('tech', 1), ('pf', 1)],
        'TBANQUILLO-B':             [('tech', 1), ('pf', 1)],
        'TDESCALIFICANTE':          [('tech', 1), ('pf', 1)], # Ojo: a veces descalificante no es técnica, depende regla
        'TECNICA-E':                [('tech', 1)], # Entrenador?
        'FALTA-COMETIDA':           [('pf', 1)],

        # Bloqueos
        'TAPON-RECIBIDO':           [('ba', 1)],
        'TAPON-COMETIDO':           [('blk', 1)],
        'ASISTENCIA':               [('ast', 1)],
    }

    def __init__(self, home_id, away_id, match_id):
        self.match_id = match_id

        self.home_id = home_id
        self.away_id = away_id
        
        # Estados
        self.period_active = False
        self.current_period = 0
        
        # Lineups (Sets)
        self.h_lineup = set()
        self.a_lineup = set()
        
        # Buffer de cambios
        self.pending_subs = [] 
        
        # Resultados
        self.stints = []
        self.current_stint = None
        self.n_stints = 0
        
        # Boxscore acumulado: {pid: {pts: 10, reb: 5...}}

    def process_event(self, etype, etime, tid, pid):
        """
        Método maestro que recibe un evento crudo y decide qué hacer.
        """
        if etype in self.IGNORE_EVENTS:
            return

        # 1. Gestión de Tiempo
        if etype == 'INICIO-PERIODO':
            self._start_period(etime)
            return
        elif etype in ['FINAL-PERIODO', 'FINAL-PARTIDO']:
            self._end_period(etime)
            return

        # 2. Gestión de Sustituciones (Buffer)
        if etype in ['CAMBIO-JUGADOR-SALE', 'CAMBIO-JUGADOR-ENTRA']:
            self._add_to_sub_buffer(tid, pid, etype)
            return
        
        # 3. Commit de Sustituciones (Si hay un evento de juego y hay cambios pendientes)
        if self._should_commit_subs(etype):
            self._commit_substitution_block(etime)

        # 4. Registrar Estadísticas
        self._register_stat(tid, etype, pid)

    def get_results(self):
        """Retorna DataFrames limpios al finalizar."""
        stints = pd.DataFrame([s.to_dict() for s in self.stints])
        rows = []
        for s in self.stints:
            rows.extend(s.to_player_rows())
        stints_per_player = pd.DataFrame(rows)
        return stints, stints_per_player
        # df_stints = pd.DataFrame(self.stints)
        # Convertir dict de dicts a DataFrame para boxscore
        # df_boxscore = pd.DataFrame.from_dict(self.player_boxscore, orient='index')
        # df_boxscore.index.name = 'player_id'
        # df_boxscore = df_boxscore.reset_index()
        # return df_stints

    # --- Métodos Internos (Privados) ---

    def _init_new_stint(self, etime):
        s = Stint(self.match_id, self.n_stints, etime, self.current_period,
                      self.h_lineup, self.a_lineup, self.home_id, self.away_id, self.COLS)
        self.n_stints += 1
        return s

    def _start_period(self, etime):
        if self.pending_subs:
            self._apply_pending_subs()
        self.period_active = True
        self.current_period += 1
        self.current_stint = self._init_new_stint(etime)

    def _end_period(self, etime):
        if self.period_active and self.current_stint:
            if self.pending_subs:
                self._apply_pending_subs()
            self.current_stint.close(etime)
            self.stints.append(self.current_stint)
            
        self.current_stint = None
        self.period_active = False
        self.h_lineup.clear()
        self.a_lineup.clear()

    def _add_to_sub_buffer(self, tid, pid, etype):
        self.pending_subs.append({'tid': tid, 'pid': pid, 'type': etype})

    def _should_commit_subs(self, etype):
        # Si hay pendientes y NO es un evento de cambio, cerramos el bloque
        return len(self.pending_subs) > 0

    def _apply_pending_subs(self):
        for sub in self.pending_subs:
            target_set = self.h_lineup if sub['tid'] == self.home_id else self.a_lineup
            if sub['type'] == 'CAMBIO-JUGADOR-SALE':
                target_set.discard(sub['pid'])
            else:
                target_set.add(sub['pid'])
        self.pending_subs = []

    def _commit_substitution_block(self, etime):
        # Cerramos stint actual
        if self.current_stint:
            self.current_stint.close(etime)
            self.stints.append(self.current_stint)
        
        # Aplicamos cambios
        self._apply_pending_subs()
        # Abrimos nuevo stint
        self.current_stint = self._init_new_stint(etime)

    def _register_stat(self, tid, etype, pid):
        # Usamos el diccionario STAT_MAPPING para obtener las reglas O(1)
        if etype not in self.STAT_MAPPING:
            return

        # 1. Determinar target Team Stint
        # Si el periodo está activo usamos current, sino (tiros libres post reloj) el ultimo stint
        target_stint = self.current_stint if self.period_active else (self.stints[-1] if self.stints else None)
        # prefix = 'h' if tid == self.home_id else 'a'

        for col, val in self.STAT_MAPPING[etype]:# Lista de (col, val)
            # Update Team Stint
            if target_stint:
                target_stint.add_stat(tid, col, val, pid)
                # target_stint[f'{prefix}_{col}'] += val


def process_events_to_stints(matches, events):
    match_ids = events['match_id'].unique()#matches['match_id'].unique()
    logger.info(f"Received {len(events)} pbp events for {len(match_ids)} matches")

    matches = matches.copy().set_index('match_id') 
    all_stints = []
    all_stints_per_players = []
    
    for m_id in match_ids:
        match_row = matches.loc[m_id]
        if match_row.empty: continue
        match_events = events[events['match_id'] == m_id]
        if match_events.empty: continue
        home_id = match_row['home_id']
        away_id = match_row['away_id']
        parser = StintParser(home_id, away_id, m_id)
        events_sorted = match_events.sort_values(by=['seq'], ascending=True)
        
        for row in events_sorted.itertuples(index=False):
            parser.process_event(
                etype=row.event_type,
                etime=row.clk,
                tid=row.team_id,
                pid=row.player_id
            )
        
        stints, stints_per_player  = parser.get_results()
        logger.info(f"Transformed match_id {m_id} matches into {len(stints)} stints")
        all_stints.append(stints); all_stints_per_players.append(stints_per_player)

    final_stints = pd.concat(all_stints, ignore_index=True) if all_stints else pd.DataFrame()
    final_player_stints = pd.concat(all_stints_per_players, ignore_index=True) if all_stints_per_players else pd.DataFrame()
    logger.info(f"Transformed {len(matches)} matches into {len(final_stints)} stints")
    return final_stints, final_player_stints


def get_match_result(row):
    try:
        h = float(row['home_pts'])
        a = float(row['away_pts'])
        if h > a:
            return 'HOME_WIN'
        elif a > h:
            return 'AWAY_WIN'
        else:
            raise ValueError("No hay empate en basket...")
    except Exception:
        return 'UNKNOWN'

def transform_to_gold(silver_data):
    """
    Transforms Silver tables into Gold dimensional/fact tables.
    """
    logger.info("Starting transformation from Silver to Gold...")
    
    matches = silver_data['matches']
    pbps = silver_data['pbps']
    players = silver_data['players']
    teams = silver_data['teams']
    competitions = silver_data['competitions']
    
    # 1. Process PBP events to stints and boxscores
    # Only process played matches that have PBP events
    played_matches = matches[matches['status'] != 'NO_COMENZADO'].copy()
    
    logger.info(f"Processing stints for {len(played_matches)} played matches...")
    df_dim_stints, df_fact_player_stints = process_events_to_stints(played_matches, pbps)
    
    
    # 4. Build dim_match (copy matches, add 'result')
    df_dim_match = matches.copy()
    if not df_dim_match.empty:
        df_dim_match['result'] = df_dim_match.apply(get_match_result, axis=1)
        
    # 5. Build dim_player (copy players)
    df_dim_player = players.copy()
    
    # 6. Build dim_team (copy teams)
    df_dim_team = teams.copy()
    
    # 7. Build dim_competition (copy competitions)
    df_dim_competition = competitions.copy()
    
    logger.info("=" * 60)
    logger.info("TRANSFORMATION SUMMARY (GOLD)")
    logger.info("=" * 60)
    logger.info(f"  - fact_stints_per_player:  {len(df_fact_player_stints)} records")
    logger.info(f"  - dim_player:          {len(df_dim_player)} records")
    logger.info(f"  - dim_stint:           {len(df_dim_stints)} records")
    logger.info(f"  - dim_match:           {len(df_dim_match)} records")
    logger.info(f"  - dim_team:            {len(df_dim_team)} records")
    logger.info(f"  - dim_competition:     {len(df_dim_competition)} records")
    logger.info("=" * 60)
    
    return {
        'fact_player_stints': df_fact_player_stints,
        'dim_stint': df_dim_stints,
        'dim_match': df_dim_match,
        'dim_player': df_dim_player,
        'dim_team': df_dim_team,
        'dim_competition': df_dim_competition
    }
