"""
Carga y persistencia en S3 para la Capa Bronze.
Maneja perfiles, almacenamiento de JSONs crudos y verificación paralela de estado.
"""
import os
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List, Tuple, Optional

import boto3
from botocore.config import Config

from src.config import S3_BUCKET_NAME, S3_RAW_PREFIX

MAX_WORKERS = 100
PROFILES_PREFIX = f"{S3_RAW_PREFIX}/profiles"

def get_s3_client(max_pool: int = MAX_WORKERS):
    """Crea un cliente S3 con pool de conexiones configurado."""
    if not S3_BUCKET_NAME:
        raise ValueError("S3_BUCKET_NAME no está configurado en las variables de entorno.")
    return boto3.client("s3", config=Config(max_pool_connections=max_pool))

# --- Manejo de Perfiles y Sesiones en S3 ---

def get_available_profiles(s3_client=None) -> List[str]:
    """Lista todos los perfiles guardados en S3 (raw/profiles/)."""
    if not S3_BUCKET_NAME:
        return []

    s3 = s3_client or get_s3_client()
    ids = []
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=f"{PROFILES_PREFIX}/"):
            if "Contents" in page:
                for obj in page["Contents"]:
                    key = obj["Key"]
                    if key.endswith(".json"):
                        filename = os.path.basename(key)
                        ids.append(filename.replace(".json", ""))
    except Exception:
        pass
    return ids

def load_profile_state(profile_id: str, s3_client=None) -> Optional[Dict[str, Any]]:
    """Descarga el estado de un perfil desde S3."""
    s3 = s3_client or get_s3_client()
    key = f"{PROFILES_PREFIX}/{profile_id}.json"
    try:
        resp = s3.get_object(Bucket=S3_BUCKET_NAME, Key=key)
        return json.loads(resp["Body"].read().decode("utf-8"))
    except s3.exceptions.NoSuchKey:
        return None
    except Exception as e:
        logging.getLogger(__name__).warning(f"Error reading profile {profile_id} from S3: {e}")
        return None

def save_profile_state(profile_id: str, state: Dict[str, Any], s3_client=None):
    """Guarda el estado de una sesión en S3."""
    s3 = s3_client or get_s3_client()
    key = f"{PROFILES_PREFIX}/{profile_id}.json"
    try:
        s3.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=key,
            Body=json.dumps(state, indent=4, ensure_ascii=False)
        )
    except Exception as e:
        logging.getLogger(__name__).error(f"Error writing profile {profile_id} to S3: {e}")

# --- Guardado de Datos Crudos en S3 ---

def save_raw_json(data: Dict[str, Any], folder_name: str, file_name: str, s3_client=None):
    """Guarda un payload JSON en S3 bajo el prefijo raw/{folder_name}/{file_name}."""
    s3 = s3_client or get_s3_client()
    key = f"{S3_RAW_PREFIX}/{folder_name}/{file_name}"
    try:
        s3.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=key,
            Body=json.dumps(data, ensure_ascii=False, indent=4),
            ContentType="application/json"
        )
    except Exception as e:
        logging.getLogger(__name__).error(f"CRITICAL ERROR: Failed to upload {key} to S3: {e}")
        raise

def clear_raw_prefix(folder_name: str, s3_client=None):
    """Elimina todos los objetos bajo un prefijo en la zona raw (ej. upcoming)."""
    s3 = s3_client or get_s3_client()
    prefix = f"{S3_RAW_PREFIX}/{folder_name}/"
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=prefix):
            if "Contents" in page:
                objects = [{"Key": obj["Key"]} for obj in page["Contents"]]
                s3.delete_objects(Bucket=S3_BUCKET_NAME, Delete={"Objects": objects})
        logging.getLogger(__name__).info(f"Cleaned raw S3 prefix: {folder_name}")
    except Exception as e:
        logging.getLogger(__name__).error(f"Error cleaning S3 prefix {prefix}: {e}")

# --- Verificación de Partidos Finalizados en S3 (Incremental) ---

def is_match_finalized(folder_name: str, file_name: str, s3_client=None) -> bool:
    """Verifica si el partido ya existe en S3 y está con estado FINALIZADO."""
    s3 = s3_client or get_s3_client()
    key = f"{S3_RAW_PREFIX}/{folder_name}/{file_name}"
    try:
        resp = s3.get_object(Bucket=S3_BUCKET_NAME, Key=key)
        stored_data = json.loads(resp["Body"].read().decode("utf-8"))
        return stored_data.get("partido", {}).get("estado_partido") == "FINALIZADO"
    except s3.exceptions.NoSuchKey:
        return False
    except Exception as e:
        logging.getLogger(__name__).error(f"Error checking S3 key {key}: {e}")
        return False

def filter_pending_matches_parallel(
    finished_matches: Dict[str, Dict[str, Any]],
    season_id: str,
    logger: Optional[logging.Logger] = None,
    max_workers: int = MAX_WORKERS
) -> List[Tuple[str, Dict[str, Any], str, str, str]]:
    """
    Verifica en paralelo contra S3 qué archivos faltan por descargar.
    Devuelve la lista de candidatos pendientes: (internal_id, game, prefix, folder_name, file_name).
    """
    log = logger or logging.getLogger(__name__)
    if not finished_matches:
        return []

    prefixes = ["pbp", "agg_by_player", "agg_by_team"]
    candidates = []
    for internal_id, game in finished_matches.items():
        for prefix in prefixes:
            folder_name = f"{prefix}_{season_id}"
            file_name = f"{internal_id}.json"
            candidates.append((internal_id, game, prefix, folder_name, file_name))

    log.info(f"Checking S3 status for {len(candidates)} files in parallel...")

    s3 = get_s3_client(max_pool=min(max_workers, len(candidates)))

    def check_candidate(cand):
        _, _, prefix, folder, file = cand
        return cand, is_match_finalized(folder, file, s3_client=s3)

    to_fetch = []
    worker_count = min(max_workers, len(candidates))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        for cand, is_fin in executor.map(check_candidate, candidates):
            internal_id, _, prefix, folder, file = cand
            if is_fin:
                log.info(f"  -> [{prefix}] Already finalized in S3 ({folder}/{file}). Skipping.")
            else:
                to_fetch.append(cand)

    log.info(f"S3 checks complete: {len(to_fetch)} of {len(candidates)} files need to be fetched.")
    return to_fetch
