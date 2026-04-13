import pandas as pd
import numpy as np
import networkx as nx
from datetime import datetime
from dataclasses import dataclass, field
from rapidfuzz import process, fuzz




# Asumo que estos módulos están en tu estructura de carpetas local
from src.config import UNKNOWN_NAME_FIX
from src.utils import (
    clean_text,
    NAMESPACE, 
    create_pbp_uuid, 
    create_match_id, 
    create_competition_id, 
    create_team_id, 
    create_player_id
)

@dataclass
class RawBasketballData:
    """Intermediate storage for raw dictionaries before cleaning."""
    matches: list[dict] = field(default_factory=list)
    teams: list[dict] = field(default_factory=list)
    pbp_events: list[dict] = field(default_factory=list)
    players: list[dict] = field(default_factory=list)
    competitions: list[dict] = field(default_factory=list)

def parse_match_datetime(s: str) -> datetime:
    timestamp = s.split("_")[-1].replace('.json', '')
    return datetime.strptime(timestamp, "%Y%m%d%H%M")

def _fix_player_name(player, UNKNOWN_NAME_FIX):
    nombre = player.get('player_name', 'NOMBRE')
    player_id = player.get('player_id')
    if nombre == 'NOMBRE' and player_id in UNKNOWN_NAME_FIX:
        return UNKNOWN_NAME_FIX[player_id]
    return clean_text(nombre)



def get_pbp_df(lista_pbp_dfs, lookup_teams, lookup_matches, lookup_players):
    if not lista_pbp_dfs:
        return pd.DataFrame()

    df = pd.DataFrame(lista_pbp_dfs).rename(columns={
        'autoincremental_id' : 'seq',
        'equipo_id' : 'team_raw_id',
        'componente_id' : 'player_raw_id',
        'numero_periodo' : 'period',
        'tiempo_partido' : 'clk',
        'accion_tipo' : 'event_type',
        'posicion_x' : 'x',
        'posicion_y' : 'y',
        'dorsal' : 'jersey',
        'zona' : 'zone',
        'informacion_adicional' : 'note',
    })

   
    for col in ['team_raw_id', 'player_raw_id']:
        df[col] = df[col].astype(str)

    # Standardize types
    lookup_teams['raw_id'] = lookup_teams['raw_id'].astype(str)
    lookup_players['raw_id'] = lookup_players['raw_id'].astype(str)
    lookup_matches['raw_id'] = lookup_matches['raw_id'].astype(str)

    cols_to_replace = ['team_raw_id', 'player_raw_id', 'jersey']
    df[cols_to_replace] = df[cols_to_replace].replace(['-1', -1], None)

    mask = df['player_raw_id'].isin(lookup_players['raw_id'].unique())
    df.loc[~mask, 'player_raw_id'] = None
 

    # --- TEAM MERGE ---
    # Rename lookup column first to avoid 'raw_id' name collision
    teams_renamed = lookup_teams.rename(columns={'raw_id': 'team_raw_id'})
    
    df = df.merge(
        teams_renamed[['team_raw_id', 'team_id']], 
        on='team_raw_id', 
        validate='m:1', 
        how='left'
    ).drop(columns=['team_raw_id'])

    # --- PLAYER MERGE ---
    players_renamed = lookup_players.rename(columns={
        'raw_id': 'player_raw_id', 
    })
    
    df = df.merge(
        players_renamed[['player_raw_id', 'player_id']], 
        on='player_raw_id', 
        validate='m:1', 
        how='left'
    )

    assert df.loc[mask, 'player_id'].isna().sum() == 0 
    df = df.drop(columns=['player_raw_id'])

    matches_renamed = lookup_matches.rename(columns={
        'raw_id': 'match_raw_id'}
    )
    df = df.rename(columns={'raw_id': 'match_raw_id'}).merge(
        matches_renamed[['match_raw_id', 'match_id']], 
        on='match_raw_id', 
        validate='m:1', 
        how='left'
    )
    
    assert df['match_raw_id'].isna().sum() == 0 
    df = df.drop(columns=['match_raw_id'])

    df['pbp_id'] = df.apply(create_pbp_uuid, axis=1)
    df = df.drop_duplicates(subset=['pbp_id'], keep='first')
    # print(df[~df['team_id'].isna()])
    # raise ValueError('adssads<')
    
    columns = ['seq', 'period', 'clk', 'event_type', 'jersey', 'x', 'y', 'zone', 
               'note', 'team_id', 'player_id', 'match_id', 'pbp_id']
    
    return df[columns]





def get_matches_df(matches, df_comp, lookup_teams):
    if not matches:
        return pd.DataFrame()
    
    df = pd.DataFrame(matches)
    # df = df[(df['idlocal'] != 0) & (df['idlocal'].notna())].copy()
    
    if df.empty:
        return df
    
    df['date'] = pd.to_datetime(df['raw_id'].apply(parse_match_datetime))

    df = df.merge(df_comp[['comp_name', 'id_comp']],
        on='comp_name',
        how='left',
        validate='m:1')

    lookup_teams = lookup_teams.rename(columns = {'raw_id': 'team_raw_id'})

    df = df.merge(
            lookup_teams,
            left_on='idlocal', 
            right_on='team_raw_id', 
            how='left', 
            validate='m:1') \
        .rename(columns={'team_id': 'home_id'})\
        .drop(columns=['team_raw_id']) \
        .merge(
            lookup_teams,
            left_on='idvisitante',
            right_on='team_raw_id',
            how='left',
            validate='m:1') \
        .rename(columns={'team_id': 'away_id'}) \
        .drop(columns=['team_raw_id'])

    df['match_id'] = df.apply(lambda r: create_match_id(r['local'], r['visitante'], r['date']), axis=1)
    df = df.drop_duplicates(subset=['match_id'], keep='first')

    rename_map = {
        'estado_partido': 'status',
        'tanteo_local': 'home_pts',
        'tanteo_visitante': 'away_pts',
        'numperiodos_total': 'periods',
        'duracion_partido_mm': 'total_duration_mm',
        'duracion_periodo_extra_mm': 'extra_duration_mm',
    }
    df = df.rename(columns=rename_map)

    final_columns = ['match_id', 'home_id', 'away_id', 'id_comp', 'date', 'status',  
                     'home_pts', 'away_pts', 'periods', 'total_duration_mm', 'extra_duration_mm']
    
    return df[final_columns], df[['match_id', 'raw_id']].copy()

def get_teams_df(raw_teams):
    if not raw_teams:
        return pd.DataFrame()
    
    df = pd.DataFrame(raw_teams)
    df['raw_id'] = df['team_id']
    df['team_name'] = df['team_name'].apply(clean_text)
    df['team_id'] = df['team_name'].apply(create_team_id)
    lookup = df[['team_id', 'raw_id']].drop_duplicates(subset=['raw_id'], keep='first')
    df_final = df.drop_duplicates(subset=['team_id'], keep='first')[['team_id', 'team_name']]
    return df.drop(columns=['raw_id']), lookup

def get_players_df(raw_players, threshold=95):
    if not raw_players:
        return pd.DataFrame()

    df = pd.DataFrame(raw_players) \
        .rename(columns={'IdJugador': 'player_id', 'Nombre': 'player_name'}) \
        .drop(columns=['IdJugadorFoto'], errors='ignore')

    df['player_name'] = df.apply(lambda row: _fix_player_name(row, UNKNOWN_NAME_FIX), axis=1)
    df['raw_id'] = df['player_id']
    
    is_placeholder = df['player_name'].str.upper().str.strip() == "NOMBRE"
    df_valid = df[~is_placeholder].copy()
    df_placeholders = df[is_placeholder].copy()

    if not df_valid.empty:
        df_valid['name_clean'] = df_valid['player_name'].str.replace(',', '').str.replace(r'\s+', ' ', regex=True).str.strip()
        unique_names = df_valid['name_clean'].unique().tolist()
        
        G = nx.Graph()
        G.add_nodes_from(unique_names)
        
        for i, name in enumerate(unique_names):
            matches = process.extract(name, unique_names[i+1:], scorer=fuzz.token_set_ratio, score_cutoff=threshold)
            for match in matches:
                G.add_edge(name, match[0])
                
        name_mapping = {}
        for cluster in nx.connected_components(G):
            canonical_name = max(list(cluster), key=len)
            for name in cluster:
                name_mapping[name] = canonical_name
        
        df_valid['player_name'] = df_valid['name_clean'].map(name_mapping)
        df_valid['player_id'] = df_valid['player_name'].apply(create_player_id)
        df_valid = df_valid.drop(columns=['name_clean'])

    if not df_placeholders.empty:
        df_placeholders['player_id'] = "UNKNOWN_" + df_placeholders['raw_id'].astype(str)

    df = pd.concat([df_valid, df_placeholders], ignore_index=True)
    lookup = df[['player_id', 'raw_id']].drop_duplicates(subset=['raw_id'], keep='first')
    df_final = df.drop_duplicates(subset=['player_id'], keep='first')[['player_id', 'player_name']]
    return df_final, lookup

def get_competitions_df(raw_competitions) -> pd.DataFrame:
    if len(raw_competitions) == 0:
        return pd.DataFrame()

    df = pd.DataFrame(raw_competitions)
    df['id_comp'] = df['comp_name'].apply(create_competition_id)
    df = df.drop_duplicates(subset=['id_comp'], keep='first')
    return df



def parse_payload_to_raw(payload: list) -> RawBasketballData:
    raw_storage = RawBasketballData()
    teams = {}
    
    # Helper para limpiar IDs: convierte a string, quita espacios y decimales
    def clean_id(val):
        if val is None: return None
        s = str(val).strip().replace('.0', '') # "105.0" -> "105"
        return s if s not in ['0', '', 'nan', 'None'] else None

    entry = {}
    for comp_name in payload:
        entry['competition'] = comp_name
        raw_storage.competitions.append({'comp_name': comp_name})
        comp_payload = payload[comp_name]
        entry['data'] = [(game, comp_payload[game]['pbp']) for game in comp_payload]
        for filename, pbp in entry['data']:
            if pbp.get('error') == 'sin datos':
                continue

            # 1. Match Info
            match_info = pbp.get('partido', {}).copy()
            match_info['raw_id'] = filename
            match_info['comp_name'] = comp_name
            
            # --- CORRECCIÓN 1: Limpieza inmediata de IDs ---
            raw_id_local = clean_id(match_info.get('idlocal'))
            raw_id_visit = clean_id(match_info.get('idvisitante'))
            
            # Actualizamos el match_info con los IDs limpios (o None si eran '0')
            match_info['idlocal'] = raw_id_local
            match_info['idvisitante'] = raw_id_visit

            raw_storage.matches.append(match_info)

            # --- CORRECCIÓN 2: Solo agregar a 'teams' si el ID es válido ---
            if raw_id_local: 
                if raw_id_local not in teams:
                    teams[raw_id_local] = {
                        'team_id': raw_id_local, # Ahora es string seguro
                        'team_name': str(match_info['local']).strip(),
                        'raw_id': raw_id_local # Agregado para consistencia con tu merge anterior
                    }
            
            if raw_id_visit:
                if raw_id_visit not in teams:
                    teams[raw_id_visit] = {
                        'team_id': raw_id_visit,
                        'team_name': str(match_info['visitante']).strip(),
                        'raw_id': raw_id_visit
                    }

            # 2. PBP Events
            acciones = pbp.get('envivo', {}).get('historialacciones', [])
            for action in acciones:
                action['raw_id'] = filename
                raw_storage.pbp_events.append(action)

            # 3. Players
            jug_ott = pbp.get('EnVivoJugadoresOTT', {})
            raw_storage.players.extend(jug_ott.get('JugadoresEnVivoLocal', []))
            raw_storage.players.extend(jug_ott.get('JugadoresEnVivoVisitante', []))


    # --- CORRECCIÓN 3: Lógica de Backfill mejorada ---
    
    # Mapa de Nombres -> IDs (solo de los que pudimos capturar bien)
    team_name_to_id = {
        t['team_name']: t['team_id'] 
        for t in teams.values()
    }

    for mat in raw_storage.matches:
        # Chequeamos LOCAL
        if not mat.get('idlocal'): # Si es None o vacío
            nlocal = str(mat.get('local')).strip()
            if nlocal in team_name_to_id:
                mat['idlocal'] = team_name_to_id[nlocal]
                # logging.info(f"Fixed Local ID for {nlocal} in match {mat['raw_id']}")
            else:
                logging.warning(f"ID Faltante IRRECUPERABLE: Local '{nlocal}' en {mat['raw_id']}")

        # Chequeamos VISITANTE (Independiente del local!)
        if not mat.get('idvisitante'): # Si es None o vacío
            nvisitante = str(mat.get('visitante')).strip()
            if nvisitante in team_name_to_id:
                mat['idvisitante'] = team_name_to_id[nvisitante]
                # logging.info(f"Fixed Away ID for {nvisitante} in match {mat['raw_id']}")
            else:
                logging.warning(f"ID Faltante IRRECUPERABLE: Visitante '{nvisitante}' en {mat['raw_id']}")

    
    # Convertir diccionario a lista para el output
    # Aseguramos que teams_raw_id esté presente ya que lo usas en el merge
    raw_storage.teams = []
    for t_id, t_data in teams.items():
        # Nos aseguramos que raw_id exista para el merge posterior
        if 'raw_id' not in t_data:
             t_data['raw_id'] = t_id
        raw_storage.teams.append(t_data)

    return raw_storage



def transform_pbp_data(payload):
    parsed_entities = parse_payload_to_raw(payload)
    
    df_competitions = get_competitions_df(parsed_entities.competitions)
    df_players, lookup_players = get_players_df(parsed_entities.players)
    df_teams, lookup_teams = get_teams_df(parsed_entities.teams)
    df_matches, lookup_matches = get_matches_df(parsed_entities.matches, df_competitions, lookup_teams)

    assert len(df_matches) == len(parsed_entities.matches), f"{len(df_matches)} != {len(parsed_entities.matches)}"
    
    df_pbps = get_pbp_df(
        parsed_entities.pbp_events,
        lookup_teams, 
        lookup_matches,
        lookup_players
    )
       
    return df_pbps, df_matches, df_teams, df_players, df_competitions