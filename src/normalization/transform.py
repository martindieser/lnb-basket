import pandas as pd
import numpy as np
import networkx as nx
import logging
from datetime import datetime
from dataclasses import dataclass, field
from rapidfuzz import process, fuzz, utils



from src.config import UNKNOWN_NAME_FIX, get_logger
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
    logger = get_logger()
    if not lista_pbp_dfs:
        logger.warning("No hay eventos Play-by-Play para procesar.")
        return pd.DataFrame()

    logger.info(f"Transformando {len(lista_pbp_dfs)} eventos Play-by-Play...")

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

    lookup_teams['raw_id'] = lookup_teams['raw_id'].astype(str)
    lookup_players['raw_id'] = lookup_players['raw_id'].astype(str)
    lookup_matches['raw_id'] = lookup_matches['raw_id'].astype(str)

    cols_to_replace = ['team_raw_id', 'player_raw_id', 'jersey']
    df[cols_to_replace] = df[cols_to_replace].replace(['-1', -1], None)

    mask = df['player_raw_id'].isin(lookup_players['raw_id'].unique())
    df.loc[~mask, 'player_raw_id'] = None
 
    teams_renamed = lookup_teams.rename(columns={'raw_id': 'team_raw_id'})
    df = df.merge(
        teams_renamed[['team_raw_id', 'team_id']], 
        on='team_raw_id', 
        validate='m:1', 
        how='left'
    ).drop(columns=['team_raw_id'])

    players_renamed = lookup_players.rename(columns={'raw_id': 'player_raw_id'})
    df = df.merge(
        players_renamed[['player_raw_id', 'player_id']], 
        on='player_raw_id', 
        validate='m:1', 
        how='left'
    )
    assert df.loc[mask, 'player_id'].isna().sum() == 0 
    df = df.drop(columns=['player_raw_id'])

    matches_renamed = lookup_matches.rename(columns={'raw_id': 'match_raw_id'})
    df = df.rename(columns={'raw_id': 'match_raw_id'}).merge(
        matches_renamed[['match_raw_id', 'match_id']], 
        on='match_raw_id', 
        validate='m:1', 
        how='left'
    )
    assert df['match_raw_id'].isna().sum() == 0 
    
    unmapped_events = df[df['match_id'].isna()]
    if not unmapped_events.empty:
        logger.warning(f"Se encontraron {len(unmapped_events)} eventos Play-by-Play que no pudieron ser asociados a ningún partido (match_id es nulo).")
        sample_raw_ids = unmapped_events['match_raw_id'].unique()[:5]
        logger.warning(f"  - Ejemplos de raw_id de partidos no mapeados: {list(sample_raw_ids)}")

    df = df.drop(columns=['match_raw_id'])

    df['pbp_id'] = df.apply(create_pbp_uuid, axis=1)
    original_count = len(df)
    df = df.drop_duplicates(subset=['pbp_id'], keep='first')
    logger.info(f"PBP completo. Mapeados {len(df)} eventos únicos (eliminados {original_count - len(df)} duplicados).")
    
    columns = ['seq', 'period', 'clk', 'event_type', 'jersey', 'x', 'y', 'zone', 
               'note', 'team_id', 'player_id', 'match_id', 'pbp_id']
    return df[columns]

def get_matches_df(matches, df_comp, lookup_teams):
    logger = get_logger()
    if not matches:
        logger.warning("No hay partidos para transformar.")
        return pd.DataFrame(), pd.DataFrame()
    
    df = pd.DataFrame(matches)
    if df.empty:
        return df, pd.DataFrame()
    
    df['date'] = pd.to_datetime(df['raw_id'].apply(parse_match_datetime))
    df = df.merge(df_comp[['comp_name', 'id_comp']], on='comp_name', how='left', validate='m:1')
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
    
    # Detectar duplicados de partidos antes de eliminarlos
    # Esto se debe a que por alguna razón existe el partido NO_COMENZADO y el FINALIZADO simultaneamente
    # Me paso cuando deje mucho tiempo sin correr el scraper.
    # En estos casos basta con priorizar el estado del partido FINALIZADO
    df = pd.concat([
            df[df['estado_partido'] == 'FINALIZADO'],
            df[df['estado_partido'] == 'NO_COMENZADO']
        ], ignore_index= True)

    # Eliminamos duplicados (al estar los jugados primero, en el caso de simultaneadad los conserva)
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
    
    # Fill defaults if columns are missing
    for col in ['periods', 'total_duration_mm', 'extra_duration_mm']:
        if col not in df.columns:
            df[col] = 4 if col == 'periods' else (10 if col == 'total_duration_mm' else 5)
            
    logger.info(f"Transformación de partidos completada. {len(df)} partidos limpios obtenidos.")
    return df[final_columns], df[['match_id', 'raw_id']].copy()

def get_teams_df(raw_teams):
    logger = get_logger()
    if not raw_teams:
        logger.warning("No hay equipos para procesar.")
        return pd.DataFrame(), pd.DataFrame()
    
    logger.info(f"Procesando {len(raw_teams)} entradas de equipos...")
    
    df = pd.DataFrame(raw_teams)
    df['raw_id'] = df['team_id']
    df['team_name'] = df['team_name'].apply(clean_text)
    df['team_id'] = df['team_name'].apply(create_team_id)
    lookup = df[['team_id', 'raw_id']].drop_duplicates(subset=['raw_id'], keep='first')
    df_final = df.drop_duplicates(subset=['team_id'], keep='first')[['team_id', 'team_name']]
    logger.info(f"Deduplicación de equipos completada. Encontrados {len(df_final)} equipos únicos.")
    return df_final, lookup

def get_players_df(raw_players, players_details, threshold=95):
    logger = get_logger()
    if not raw_players:
        logger.warning("No hay jugadores para procesar.")
        return pd.DataFrame(), pd.DataFrame()
    
    logger.info(f"Procesando {len(raw_players)} entradas de jugadores...")
    logger.info(f"Procesando player_details {len(players_details)}")

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
        logger.debug(f"Ejecutando deduplicación difusa en {len(unique_names)} nombres de jugadores únicos...")
        
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
        logger.info(f"Deduplicación completada: {len(unique_names)} nombres agrupados en {len(df_valid['player_name'].unique())} jugadores únicos.")

    if not df_placeholders.empty:
        df_placeholders['player_id'] = "UNKNOWN_" + df_placeholders['raw_id'].astype(str)
        logger.info(f"Encontrados {len(df_placeholders)} jugadores con nombre placeholder (UNKNOWN).")

    df = pd.concat([df_valid, df_placeholders], ignore_index=True)
    lookup = df[['player_id', 'raw_id']].drop_duplicates(subset=['raw_id'], keep='first')
    df_final = df.drop_duplicates(subset=['player_id'], keep='first')[['player_id', 'player_name']].copy()

    # Inicializar columnas del esquema
    df_final['height_cm'] = None
    df_final['nationality'] = None
    df_final['birth_date'] = None

    # Enriquecer con players_details usando Fuzzy Matching si se proveen datos
    if players_details and not df_final.empty:
        pb_list = []
        for p_id, info in players_details.items():
            pb_list.append(info)

        if pb_list:
            pb_names = [p['name'] for p in pb_list]
            
            heights = []
            nationalities = []
            birth_dates = []
            match_count = 0
            
            for name in df_final['player_name']:
                clean_cabb_name = name.replace(',', ' ').strip()
                # fuzz.token_set_ratio es ideal para cruzar "APELLIDO, NOMBRE" con "Nombre Apellido"
                match = process.extractOne(
                    clean_cabb_name,
                    pb_names,
                    scorer=fuzz.token_set_ratio,
                    processor=utils.default_process,
                    score_cutoff=85  # Umbral para el matching cruzado
                )
                
                if match:
                    matched_name = match[0]
                    score = match[1]
                    matched_info = next((p for p in pb_list if p['name'] == matched_name), None)
                    if matched_info:
                        logger.info(f"Coincidencia: '{name}' asociado con '{matched_name}' (Puntaje: {score:.1f})")
                        heights.append(matched_info.get('height_cm'))
                        nationalities.append(matched_info.get('nationality'))
                        birth_dates.append(matched_info.get('birth_date'))
                        match_count += 1
                        continue
                        
                logger.warning(f"Sin coincidencia: No se encontraron detalles para el jugador '{name}'")
                heights.append(None)
                nationalities.append(None)
                birth_dates.append(None)
                
            logger.info(f"Resumen de enriquecimiento: Se asociaron con éxito {match_count}/{len(df_final)} jugadores con sus detalles.")
            df_final['height_cm'] = heights
            df_final['nationality'] = nationalities
            df_final['birth_date'] = birth_dates

    return df_final, lookup

def get_competitions_df(raw_competitions) -> pd.DataFrame:
    if len(raw_competitions) == 0:
        return pd.DataFrame()
    df = pd.DataFrame(raw_competitions)
    df['id_comp'] = df['comp_name'].apply(create_competition_id)
    df = df.drop_duplicates(subset=['id_comp'], keep='first')
    return df

def parse_payload_to_raw(payload: dict) -> RawBasketballData:
    logger = get_logger()
    logger.info(f"Parseando payload bruto con {len(payload)} competiciones...")
    raw_storage = RawBasketballData()
    teams = {}
    
    def clean_id(val):
        if val is None: return None
        s = str(val).strip().replace('.0', '')
        return s if s not in ['0', '', 'nan', 'None'] else None

    for comp_name in payload:
        raw_storage.competitions.append({'comp_name': comp_name})
        comp_payload = payload[comp_name]
        for filename in comp_payload:
            pbp = comp_payload[filename].get('pbp', {})
            if pbp.get('error') == 'sin datos':
                logger.warning(f"Omitiendo partido {filename} en competición {comp_name} por error de CABB: 'sin datos'.")
                continue

            match_info = pbp.get('partido', {}).copy()
            match_info['raw_id'] = filename
            match_info['comp_name'] = comp_name
            
            raw_id_local = clean_id(match_info.get('idlocal'))
            raw_id_visit = clean_id(match_info.get('idvisitante'))
            match_info['idlocal'] = raw_id_local
            match_info['idvisitante'] = raw_id_visit
            raw_storage.matches.append(match_info)

            if raw_id_local: 
                if raw_id_local not in teams:
                    teams[raw_id_local] = {
                        'team_id': raw_id_local,
                        'team_name': str(match_info['local']).strip(),
                        'raw_id': raw_id_local
                    }
            if raw_id_visit:
                if raw_id_visit not in teams:
                    teams[raw_id_visit] = {
                        'team_id': raw_id_visit,
                        'team_name': str(match_info['visitante']).strip(),
                        'raw_id': raw_id_visit
                    }

            acciones = pbp.get('envivo', {}).get('historialacciones', [])
            for action in acciones:
                action['raw_id'] = filename
                raw_storage.pbp_events.append(action)

            jug_ott = pbp.get('EnVivoJugadoresOTT', {})
            raw_storage.players.extend(jug_ott.get('JugadoresEnVivoLocal', []))
            raw_storage.players.extend(jug_ott.get('JugadoresEnVivoVisitante', []))

    team_name_to_id = {t['team_name']: t['team_id'] for t in teams.values()}

    for mat in raw_storage.matches:
        if not mat.get('idlocal'):
            nlocal = str(mat.get('local')).strip()
            if nlocal in team_name_to_id:
                mat['idlocal'] = team_name_to_id[nlocal]
            else:
                fake_raw_id = f"UNKNOWN_LOCAL_{create_team_id(nlocal)[:8]}"
                mat['idlocal'] = fake_raw_id
                teams[fake_raw_id] = {'team_id': fake_raw_id, 'team_name': nlocal, 'raw_id': fake_raw_id}
                team_name_to_id[nlocal] = fake_raw_id
                logger.warning(f"Generando ID provisorio {fake_raw_id} para Local '{nlocal}' en partido {mat['raw_id']}")

        if not mat.get('idvisitante'):
            nvisitante = str(mat.get('visitante')).strip()
            if nvisitante in team_name_to_id:
                mat['idvisitante'] = team_name_to_id[nvisitante]
            else:
                fake_raw_id = f"UNKNOWN_AWAY_{create_team_id(nvisitante)[:8]}"
                mat['idvisitante'] = fake_raw_id
                teams[fake_raw_id] = {'team_id': fake_raw_id, 'team_name': nvisitante, 'raw_id': fake_raw_id}
                team_name_to_id[nvisitante] = fake_raw_id
                logger.warning(f"Generando ID provisorio {fake_raw_id} para Visitante '{nvisitante}' en partido {mat['raw_id']}")


    logger.info(f"Parseo de payload completado: {len(raw_storage.matches)} partidos, {len(raw_storage.teams)} equipos, {len(raw_storage.pbp_events)} eventos, {len(raw_storage.players)} jugadores.")
    raw_storage.teams = list(teams.values())
    return raw_storage

def transform_pbp_data(payload, players_details):
    logger = get_logger()
    logger.info("Iniciando fase de transformación de datos Play-by-Play (Bronze -> Silver)...")
    parsed_entities = parse_payload_to_raw(payload)
    df_competitions = get_competitions_df(parsed_entities.competitions)
    df_players, lookup_players = get_players_df(parsed_entities.players, players_details)
    df_teams, lookup_teams = get_teams_df(parsed_entities.teams)
    df_matches, lookup_matches = get_matches_df(parsed_entities.matches, df_competitions, lookup_teams)

    # assert len(df_matches) == len(parsed_entities.matches), f"{len(df_matches)} != {len(parsed_entities.matches)}"
    
    df_pbps = get_pbp_df(parsed_entities.pbp_events, lookup_teams, lookup_matches, lookup_players)

    logger.info("=" * 60)
    logger.info("RESUMEN DE REGISTROS PROCESADOS (SILVER)")
    logger.info("=" * 60)
    logger.info(f"  - Competiciones: {len(df_competitions)}")
    logger.info(f"  - Equipos:       {len(df_teams)} (Mapeos en lookup: {len(lookup_teams)})")
    logger.info(f"  - Jugadores:     {len(df_players)} (Mapeos en lookup: {len(lookup_players)})")
    logger.info(f"  - Partidos:      {len(df_matches)}")
    logger.info(f"  - Eventos PBP:   {len(df_pbps)}")
    logger.info("=" * 60)
    return df_pbps, df_matches, df_teams, df_players, df_competitions
