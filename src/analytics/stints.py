import pandas as pd
import logging
from collections import defaultdict
from tqdm import tqdm

logger = logging.getLogger(__name__)

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

    def __init__(self, home_id, away_id):
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
        
        # Boxscore acumulado: {pid: {pts: 10, reb: 5...}}
        self.player_boxscore = defaultdict(lambda: {c: 0 for c in self.COLS})

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
        df_stints = pd.DataFrame(self.stints)
        
        # Convertir dict de dicts a DataFrame para boxscore
        df_boxscore = pd.DataFrame.from_dict(self.player_boxscore, orient='index')
        df_boxscore.index.name = 'player_id'
        df_boxscore = df_boxscore.reset_index()
        
        return df_stints, df_boxscore

    # --- Métodos Internos (Privados) ---

    def _init_new_stint(self, etime):
        new_s = {
            'start': etime, 
            'end': '00:00:00.0', 
            'nperiod': self.current_period,
            'home_lineup': self.h_lineup.copy(), 
            'away_lineup': self.a_lineup.copy(),
            'home_id' : self.home_id,
            'away_id' : self.away_id,
        }
        # Inicializar contadores en 0
        for col in self.COLS:
            new_s[f'h_{col}'] = 0
            new_s[f'a_{col}'] = 0
        return new_s

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
            self.current_stint['end'] = etime
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
            self.current_stint['end'] = etime
            # Snapshot de lineups al momento del cierre
            self.current_stint['home_lineup'] = self.h_lineup.copy()
            self.current_stint['away_lineup'] = self.a_lineup.copy()
            self.stints.append(self.current_stint)
        
        # Aplicamos cambios
        self._apply_pending_subs()
        # Abrimos nuevo stint
        self.current_stint = self._init_new_stint(etime)

    def _register_stat(self, tid, etype, pid):
        # Usamos el diccionario STAT_MAPPING para obtener las reglas O(1)
        if etype not in self.STAT_MAPPING:
            return

        stat_updates = self.STAT_MAPPING[etype] # Lista de (col, val)
        
        # 1. Determinar target Team Stint
        # Si el periodo está activo usamos current, sino (tiros libres post reloj) el ultimo stint
        target_stint = self.current_stint if self.period_active else (self.stints[-1] if self.stints else None)
        prefix = 'h' if tid == self.home_id else 'a'

        for col, val in stat_updates:
            # Update Team Stint
            if target_stint:
                target_stint[f'{prefix}_{col}'] += val
            
            # Update Player Boxscore
            if pid:
                self.player_boxscore[pid][col] += val


def process_events_to_stints(matches, events):
    match_ids = matches['match_id'].unique()
    matches = matches.copy().set_index('match_id') 
    # Acumuladores
    all_stints = []
    all_boxscores = [] 
    
    for m_id in tqdm(match_ids):
        try:
            # 1. Datos del partido
            match_row = matches.loc[m_id]
            if match_row.empty: continue
            
            home_id = match_row['home_id']
            away_id = match_row['away_id']
            
            match_events = events[events['match_id'] == m_id]
            if match_events.empty: continue
            
            # 2. Instanciar el nuevo Parser Pro
            parser = StintParser(home_id, away_id)
            
            # 3. Procesar eventos (Optimizado con itertuples)
            # Aseguramos el orden cronológico
            events_sorted = match_events.sort_values(by=['seq'], ascending=True)
            
            for row in events_sorted.itertuples(index=False):
                parser.process_event(
                    etype=row.event_type,
                    etime=row.clk,
                    tid=row.team_id,
                    pid=row.player_id
                )
            
            # 4. Obtener resultados limpios del parser
            stints_df, boxscore_df = parser.get_results()
            
            # 5. Agregar metadata (match_id)
            stints_df['match_id'] = m_id 
            boxscore_df['match_id'] = m_id
            
            all_stints.append(stints_df)
            all_boxscores.append(boxscore_df)
            
        except Exception as e:
            logger.error(f"Error on match {m_id}: {e}")
            # Quité el break para que si falla un partido siga con el resto
            continue 

    # 6. Concatenar resultados finales
    final_stints = pd.concat(all_stints, ignore_index=True) if all_stints else pd.DataFrame()
    final_boxscores = pd.concat(all_boxscores, ignore_index=True) if all_boxscores else pd.DataFrame()
    
    return final_stints, final_boxscores