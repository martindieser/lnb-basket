import logging
import random
from typing import Optional
from datetime import datetime, timedelta
from prefect import flow, task

from src.config import get_logger
from src.ingestion.load import (
    get_available_profiles,
    load_profile_state,
    save_profile_state,
    save_raw_json,
    clear_raw_prefix,
    filter_pending_matches_parallel,
)
from src.ingestion.extract import (
    create_scraper,
    extract_matches,
    extract_play_by_play,
    extract_player_stats,
    extract_team_stats,
)
from src.ingestion.transform import (
    partition_matches,
    create_upcoming_payload,
)


@task
def get_random_profile():
    logger = get_logger()
    logger.info("Selecting a random profile from S3...")
    all_profiles = get_available_profiles()
    if not all_profiles:
        logger.warning("No profiles available in S3. A new one will be registered automatically.")
        return None

    selected = random.choice(all_profiles)
    logger.info(f"Selected Random Profile: {selected}")
    return selected


@task
def execute_ingestion_phase(
    profile_id: Optional[str],
    selected_start: str,
    selected_end: str,
    league: str
):
    logger = get_logger()
    logger.info(f"--- Starting Unified Scraping Phase (Profile: {profile_id}) ---")

    # 1. EXTRACT: Inicializar cliente con estado persistido en S3 (si existe)
    state = load_profile_state(profile_id) if profile_id else None
    scraper, session = create_scraper(profile_id=profile_id, state=state, logger=logger)

    # Extraer partidos para el rango de fechas
    season_id, matches_data = extract_matches(scraper, selected_start, selected_end, league=league)

    # Sincronizar estado inicial de sesión en S3
    save_profile_state(session.profile_id, session.to_dict())

    if not matches_data:
        logger.warning(f"No matches found in range {selected_start} to {selected_end}. Skipping detail phase.")
        return "no_matches"

    logger.info(f"Found {len(matches_data)} matches for season '{season_id}'")

    # 2. TRANSFORM: Particionar upcoming vs finalizados
    upcoming_matches, finished_matches = partition_matches(matches_data)
    logger.info(f"Matches partition: {len(upcoming_matches)} upcoming, {len(finished_matches)} finished.")

    # 3. LOAD UPCOMING: Sobreescribir carpeta 'upcoming' con datos frescos
    if upcoming_matches:
        clear_raw_prefix("upcoming")
        for match_id, game in upcoming_matches.items():
            payload = create_upcoming_payload(game)
            save_raw_json(payload, "upcoming", f"{match_id}.json")
        logger.info(f"Saved {len(upcoming_matches)} upcoming matches to raw/upcoming/")

    # 4. LOAD FINISHED: Chequeo paralelo en S3 e ingesta incremental
    if finished_matches:
        pending_candidates = filter_pending_matches_parallel(finished_matches, season_id, logger=logger)

        endpoint_map = {
            "pbp": extract_play_by_play,
            "agg_by_player": extract_player_stats,
            "agg_by_team": extract_team_stats,
        }

        for internal_id, game, prefix, folder_name, file_name in pending_candidates:
            game_id = game.get("IdPartido")
            logger.info(f"Fetching {prefix} for game ID: {game_id} | {internal_id}")
            fetch_fn = endpoint_map.get(prefix)
            if fetch_fn:
                try:
                    match_data = fetch_fn(scraper, game_id)
                    save_raw_json(match_data, folder_name, file_name)
                    logger.info(f"  -> [{prefix}] Saved to S3 ({folder_name}/{file_name})")
                except Exception as e:
                    logger.error(f"  -> [{prefix}] Failed to fetch/save {file_name}: {e}")

        # Guardar estado final de sesión con todos los hashes de partidos actualizados
        save_profile_state(session.profile_id, session.to_dict())

    logger.info("--- Scraping Phase Completed Successfully ---")
    return "success"


@flow(name="cabb_ingestion_bronze")
def ingestion_flow(
    league: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """
    Capa Bronze: Recolección de datos crudos desde CABB y almacenamiento en S3 (JSON).
    """
    logger = get_logger()

    if not start_date:
        start_date = datetime.now().strftime("%Y-%m-%d")

    if not end_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_date = (start_dt + timedelta(days=7)).strftime("%Y-%m-%d")

    logger.info(f"Ingesta iniciada para el rango: {start_date} - {end_date} (Liga: '{league}')")

    profile_id = get_random_profile()

    execute_ingestion_phase(
        profile_id=profile_id,
        selected_start=start_date,
        selected_end=end_date,
        league=league,
    )


if __name__ == "__main__":
    ingestion_flow(league="liga nacional")
