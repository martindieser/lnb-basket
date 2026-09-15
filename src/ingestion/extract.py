"""
Extracción de datos desde la API móvil de CABB.
Consume el paquete privado 'cabb_client' y es agnóstico del almacenamiento S3.
"""
import logging
from typing import Dict, Any, Optional, Tuple, Union

from cabb_client import CABBScraper, CABBSession
from src.config import SCRAPER_PROXY, PROXY_CA
from src.utils import get_season_id_from_date

def create_scraper(
    profile_id: Optional[str] = None,
    state: Optional[Dict[str, Any]] = None,
    proxy: Optional[str] = None,
    verify_ssl: Optional[Union[bool, str]] = None,
    logger: Optional[logging.Logger] = None
) -> Tuple[CABBScraper, CABBSession]:
    """
    Inicializa una sesión de CABB y la instancia del scraper.
    Si se provee state, se recupera el estado de dispositivo y hashes previo.
    """
    session = CABBSession(
        profile_id=profile_id or "default_profile",
        state=state
    )

    resolved_proxy = proxy or SCRAPER_PROXY
    resolved_ssl = verify_ssl if verify_ssl is not None else (PROXY_CA if PROXY_CA else True)

    scraper = CABBScraper(
        session=session,
        proxy=resolved_proxy,
        verify_ssl=resolved_ssl,
        logger=logger,
        auto_auth=True
    )

    return scraper, session

def extract_matches(
    scraper: CABBScraper,
    start_date: str,
    end_date: str,
    league: str 
) -> Tuple[str, Dict[str, Dict[str, Any]]]:
    """
    Deduce el season_id según la fecha de inicio, resuelve la categoría en CABB
    y extrae los partidos del rango dado.
    Devuelve (season_id, matches_dict).
    """
    season_id = get_season_id_from_date(start_date)
    
    cat_id = scraper.get_category_id(league, season_id)
    if not cat_id:
        raise ValueError(f"Category ID not found in CABB API for league '{league}' and season '{season_id}'")

    matches = scraper.fetch_matches(cat_id, start_date, end_date, season_id)
    return season_id, matches

def extract_play_by_play(scraper: CABBScraper, match_id: str) -> Dict[str, Any]:
    """Descarga el Play-by-Play crudo de un partido."""
    return scraper.fetch_play_by_play(match_id)

def extract_player_stats(scraper: CABBScraper, match_id: str) -> Dict[str, Any]:
    """Descarga las estadísticas agregadas por jugador."""
    return scraper.fetch_player_stats(match_id)

def extract_team_stats(scraper: CABBScraper, match_id: str) -> Dict[str, Any]:
    """Descarga las estadísticas comparativas de equipo."""
    return scraper.fetch_team_stats(match_id)

def extract_match_details(scraper: CABBScraper, match_id: str) -> Dict[str, Any]:
    """
    Descarga los tres payloads crudos para un partido:
    - pbp: Play-by-Play
    - agg_by_player: Estadísticas agregadas por jugador
    - agg_by_team: Comparativa de equipo vs equipo
    """
    return scraper.fetch_match_details(match_id)
