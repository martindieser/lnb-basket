"""
Módulo de Ingesta (Capa Bronze).
Maneja la extracción desde CABB, transformación Bronze y persistencia en S3.
"""

from .extract import (
    create_scraper,
    extract_matches,
    extract_match_details,
    extract_play_by_play,
    extract_player_stats,
    extract_team_stats,
)
from .transform import partition_matches, create_upcoming_payload
from .load import (
    get_available_profiles,
    load_profile_state,
    save_profile_state,
    save_raw_json,
    clear_raw_prefix,
    filter_pending_matches_parallel,
)

__all__ = [
    "create_scraper",
    "extract_matches",
    "extract_match_details",
    "extract_play_by_play",
    "extract_player_stats",
    "extract_team_stats",
    "partition_matches",
    "create_upcoming_payload",
    "get_available_profiles",
    "load_profile_state",
    "save_profile_state",
    "save_raw_json",
    "clear_raw_prefix",
    "filter_pending_matches_parallel",
]
