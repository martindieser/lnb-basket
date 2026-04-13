import logging
import asyncio 
import pandas as pd
import os
import json
from typing import List, Tuple, Dict
from datetime import datetime
from dateutil.parser import parse


import mapping 
import scraper
from config import CABB_PATH


# Standard logger configuration for this module
logger = logging.getLogger(__name__)


def get_season_id_from_date(date_str):
    """
    Genera el ID de temporada (ej: liganacional20232024_basketball)
    Corte de temporada: Agosto (Mes 8).
    """
    dt = parse(str(date_str)) if isinstance(date_str, str) else date_str
    
    # Si es Agosto o después, es el inicio de la nueva temporada
    cutoff_month = 8 
    if dt.month >= cutoff_month:
        start_year = dt.year
    else:
        start_year = dt.year - 1
        
    end_year = start_year + 1
    return f"liganacional{start_year}{end_year}_basketball"


class CABBTaskHandler:
    def __init__(self, profile_id, proxy=None, internal_catid=None):
        self.data_path = CABB_PATH
        self.proxy = proxy 
        self.profile_id = profile_id
        self.internal_catid = internal_catid

        self.scraper = CABBScraper(self.profile_id, proxy=self.proxy)

        self.manager = self.scraper.cache



        logger.info(f"Initializing CABBTaskHandler for internal category: {internal_catid} | Proxy: {self.proxy}")

    def get_category_id(self, query: str):
        logger.info(f"Searching category ID for query: '{query}' and profile: {self.profile_id}")
        # Logic from 'categories' step
        # Primero busca en la caché local para ahorrar tiempo
        id_ = self.manager.get_hashed_id(self.internal_catid, type='league')
        
        if id_:
            logger.info(f"ID found in local mapping: {id_}")
            return id_

        logger.info("ID not found in cache. Starting search via CABBScraper...")
        
        # Iniciamos el scraper (usando el proxy configurado en __init__)
        status, response = self.scraper.search_category(query)
        
        if (status != 200) or (response.get('error') == 'error'):
            error_msg = f'Response error while searching category. Status: {status}, Response: {response}'
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        found = False
        # Buscamos en la respuesta de la web
        for cat in response.get('categorias', []):
            try:
                # Creamos un ID interno tentativo para comparar
                leagueid = self.manager.create_internal_league_id('basketball', cat['NombreCompeticion'])
                
                if leagueid == self.internal_catid:
                    id_ = cat['Id']
                    found = True
                    logger.info(f"Category matched and found: {cat['NombreCompeticion']} (ID: {id_})")
                
                # Registramos todas las ligas encontradas por si acaso sirvan en el futuro
                self.manager.register_league(leagueid, cat['Id'])
            except Exception as e:
                logger.warning(f"Error processing category {cat.get('NombreCompeticion', 'Unknown')}: {e}")

        if not found:
            logger.warning(f"Results obtained but none matched the internal_catid: {self.internal_catid}")

        return id_

    def convert_to_internal_id(self, row):
        """Genera un ID único interno basado en los equipos y la fecha."""
        try:
            league, sport = self.internal_catid.split('_')
            home = row['NombreEquipoLocal']
            away = row['NombreEquipoVisitante']
            date_obj = row['Fecha_Completa'].to_pydatetime()
            return self.manager.create_internal_match_id(league, sport, home, away, date_obj)
        except Exception as e:
            logger.error(f"Error generating internal_id for match row ID {row.get('IdPartido', 'Unknown')}: {e}")
            raise e

    def fetch_matches(self, cat_id: int, start_date: str, end_date: str):
        logger.info(f"Fetching matches for cat_id: {cat_id} between {start_date} and {end_date}")
        
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        # start_str = start.strftime("%Y%m%d") # No se usaban en el original, pero útiles si la API cambia
        # end_str = end.strftime("%Y%m%d")
        
        # Start Scraping
        logger.info("Starting match scraping...")
        
        # 1. Obtener Fases y Grupos (necesario para consultar partidos)
        status, response = self.scraper.category_fases(cat_id)
        if response.get('resultado') != 'correcto':
            error_msg = f"Error obtaining phases: {response.get('error')}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        try:
            # Asumimos que tomamos la primera fase y el primer grupo disponible
            id_fase = response['listaFasesGrupo'][0]['IdFase']
            id_grupo = response['listaFasesGrupo'][0]['Grupos'][0]['IdGrupo']
        except (KeyError, IndexError) as e:
            logger.error(f"Unexpected phases/groups structure: {e}")
            raise RuntimeError("Could not extract IdFase or IdGrupo from response.")
        
        # 2. Obtener lista de partidos
        status, matches_json = self.scraper.matches_on_category(cat_id, id_fase, id_grupo, '', start, end)
        
        matches_df = pd.DataFrame(matches_json.get('partidos', []))
        if matches_df.empty:
            logger.warning("No matches found in the specified date range.")
            return {}

        logger.info(f"Found {len(matches_df)} matches. Processing dates and IDs...")

        # Unificar Fecha y Hora para crear el objeto datetime completo
        matches_df['Fecha_Completa'] = pd.to_datetime(
            matches_df['Fecha'].astype(str) + ' ' + matches_df['Hora'].astype(str), 
            format='%d/%m/%Y %H:%M:%S'
        )
        
        # Generar IDs internos
        matches_df['internal_id'] = matches_df.apply(self.convert_to_internal_id, axis=1)

        # Filtrar solo los terminados
        finished_df = matches_df.copy()#[matches_df['Estado'] == 'Terminado'].copy()
        # finished_df['date'] = finished_df['date'].astype(str)
        # print(finished_df.columns)
        logger.info(f"Finished matches to process: {len(finished_df)}")

        # Registrarlos en el Cache Manager
        for _, row in finished_df.iterrows():
            self.manager.register_match(row['internal_id'], row['IdPartido'])

        for col in finished_df.select_dtypes(include=["datetime64[ns]", "datetime64[ns, UTC]"]):
            finished_df[col] = finished_df[col].astype(str)

        return finished_df.set_index('internal_id').to_dict(orient='index')

    def fetch_pbp(self, matches_ids: Dict[str, str]):
        internal_catid = self.internal_catid
        if not matches_ids:
            logger.warning("fetch_pbp called without match IDs. Exiting.")
            return
            
        logger.info(f"Starting PBP and stats download for {len(matches_ids)} matches.")

        
        output_folder = {
            'pbp' : self.scraper.play_by_play_matchdata,
            'agg_by_player' : self.scraper.aggregated_stats_by_player_on_match,
            'agg_by_team' : self.scraper.team_vs_team_stats,
        }

        total_files = len(matches_ids) * len(output_folder)
        processed_count = 0

        for internal_id, game in matches_ids.items():
            game_id = game['IdPartido']
            state = game['Estado']

            logger.info(f"Checking {internal_id} with state {state}")

            if state == 'No comenzado':
                payload = {
                    "resultado" : "correcto",
                    "partido": {
                          "tipo_acta":"ESTADÍSTICAS",
                          "estado_partido":"NO_COMENZADO",
                          "idclublocal": None,
                          "idlocal": None,
                          "local": game['NombreEquipoLocal'],
                          "color_local":"AZUL",
                          "idclubvisitante": None,
                          "idvisitante": None,
                          "visitante":game['NombreEquipoVisitante'],
                          "color_visitante":"ROJO",
                          "tanteo_local":0,
                          "tanteo_visitante":0,
                          "campoTipo":"FIBA",
                          "numperiodos":4,
                          "numperiodos_total":4,
                          "tiene_porrogas": False,
                          "duracion_periodo_normal_mm":10,
                          "duracion_periodo_extra_mm":5,
                          "tiempo_total_partido":2400,
                          "duracion_partido_mm":40,
                          "periodos": [],
                          "fechaultimaactualizacion":"",
                          "identificador_servidor":".",
                          "competicionCategoriaConPDFEstadisticas": False,
                          "IdClubLocalEncriptado":"",
                          "IdClubVisitanteEncriptado": "",
                    },
                    "envivo" : {
                         "jugadoresenpistalocal" : [],
                         "jugadoresenpistavisitante" : [],
                         "historialacciones" : [],
                         "fechaultimaactualizacion" : "",
                     },
                     "error" : "",
                     "EnVivoJugadoresOTT" : {
                         "JugadoresEnVivoLocal" : {},
                         "JugadoresEnVivoVisitante" : {},
                         "OTT" : False,
                         "UrlOTT" : "",
                     }
                }
                logger.info(f"Adding non yet started game {internal_id}")
                
                path = os.path.join(self.data_path, f'pbp_{internal_catid}')
                # >> AGREGADO:makedirs para evitar crash si es la primera corrida
                os.makedirs(path, exist_ok=True) 
                file_path = os.path.join(path, f"{internal_id}.json")
                
                # >> CAMBIO: encoding explícito para evitar quilombos en Windows
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(payload, f, ensure_ascii=False, indent=4)
                
                logger.debug(f"Successfully saved: {file_path}")
            
            elif state == 'Terminado':
                for prefix, func in output_folder.items():
                    path = os.path.join(self.data_path, f'{prefix}_{internal_catid}')
                    os.makedirs(path, exist_ok=True)
                    file_path = os.path.join(path, f"{internal_id}.json")
                    
                    # >> CAMBIO IMPORTANTE: Lógica de validación de archivo existente
                    should_scrape = True 

                    if os.path.exists(file_path):
                        try:
                            # >> CAMBIO: encoding utf-8 al leer
                            with open(file_path, 'r', encoding='utf-8') as f:
                                stored_data = json.load(f)
                                # >> CAMBIO: .get() seguro por si el json está incompleto
                                stored_state = stored_data.get('partido', {}).get('estado_partido', 'DESCONOCIDO')
                            
                            if stored_state == 'FINALIZADO':
                                logger.debug(f"[{processed_count}/{total_files}] File already exists and is FINALIZED, skipping: {file_path}")
                                should_scrape = False
                            else:
                                logger.info(f"File exists but state is '{stored_state}' (Live is Terminado). Updating file.")
                                
                        except Exception as e:
                            logger.warning(f"Error reading existing file {file_path}: {e}. Will re-scrape.")
                            should_scrape = True

                    if not should_scrape:
                        processed_count += 1
                        continue
                        
                    logger.info(f"Scraping {prefix} for GameID: {game_id} (Internal: {internal_id})")
                    try:
                        status, match_data = func(game_id)
                        
                        if status != 200 or match_data.get('resultado') == 'error':
                            logger.error(f"Failed to scrape {prefix} for game {game_id}. Status: {status}, Error: {match_data.get('error')}")
                            continue

                        # >> CAMBIO: encoding utf-8 al escribir
                        with open(file_path, 'w', encoding='utf-8') as f:
                            json.dump(match_data, f, ensure_ascii=False, indent=4)
                        
                        logger.debug(f"Successfully saved: {file_path}")

                    except Exception as e:
                        logger.exception(f"Unexpected exception processing {prefix} for game {game_id}: {e}")
                    
                    processed_count += 1
            else:
                # ignore if match is playing
                continue
            
        logger.info("fetch_pbp process finished.")