import uuid
import unicodedata
import re

# Namespace para generar UUIDs v5 consistentes (basados en nombres)
# Este ID es fijo para que tu sistema siempre genere el mismo UUID ante el mismo input
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, 'basketball.etl.system')



from dateutil.parser import parse

def get_season_id_from_date(date_str):
    """
    Generates the season ID (e.g.: liganacional20232024_basketball)
    Season cutoff: August (Month 8).
    """
    dt = parse(str(date_str)) if isinstance(date_str, str) else date_str
    
    # If it's August or later, it's the start of the new season
    cutoff_month = 8 
    if dt.month >= cutoff_month:
        start_year = dt.year
    else:
        start_year = dt.year - 1
        
    end_year = start_year + 1
    return f"liganacional{start_year}{end_year}_basketball"

def clean_text(text: str, remove_punctuation: bool = True) -> str:
    """
    Normaliza el texto: elimina tildes, caracteres especiales, 
    convierte a mayúsculas y limpia espacios.
    """
    if not text or not isinstance(text, str):
        return ""
    # 1. Normalización Unicode (NFD separa las tildes de las letras)
    text = unicodedata.normalize('NFD', text)
    
    # 2. Filtrar caracteres: mantenemos solo los que no sean marcas de acento
    text = "".join(c for c in text if unicodedata.category(c) != 'Mn')
    
    # 3. Convertir a mayúsculas
    text = text.upper()
    if remove_punctuation:
        # 4. Eliminar todo lo que no sea letras, números, espacios o paréntesis
        text = re.sub(r'[^A-Z0-9\s()]', ' ', text)
    # 5. Colapsar múltiples espacios y hacer strip
    text = " ".join(text.split())
    return text



def _generate_uuid(data_string: str) -> str:
    """Helper interno para generar un UUID v5 string."""
    return str(uuid.uuid5(NAMESPACE, data_string))



def create_pbp_uuid(row) -> str:
    """
    Crea un ID único para cada evento de Play-by-Play.
    Basado en match_id, período, reloj, secuencia y tipo de evento para máxima unicidad.
    
    Args:
        row: Diccionario o Serie con los datos del evento PBP
        
    Returns:
        str: UUID v5 único para el evento
    """
    # Componentes clave para garantizar unicidad
    match_id = row.get('match_id', 'unknown')
    seq = row.get('seq', 0)
    period = row.get('period', 0)
    clk = row.get('clk', '00:00')
    event_type = row.get('event_type', '')
    
    # Normalizar el reloj para evitar variaciones de formato
    # Ejemplo: "10:30" vs "10:30.0"
    clk_clean = str(clk).split('.')[0] if clk else '00:00'
    
    # Construir string único con componentes jerárquicos
    # match_id ya garantiza unicidad del partido
    # period + clk + seq garantizan orden temporal preciso
    # event_type agrega contexto adicional por si hubiera eventos simultáneos
    unique_str = f"{match_id}_{period}_{clk_clean}_{seq}_{event_type}"
    
    return _generate_uuid(unique_str)



def create_match_id(home_name: str, away_name: str, match_date) -> str:
    """
    Crea un ID único para un partido basado en equipos y fecha.
    """
    # Formatear fecha
    if hasattr(match_date, 'strftime'):
        date_str = match_date.strftime("%Y%m%d")
    else:
        # En caso de que venga como string o timestamp
        date_str = str(match_date)[:10].replace("-", "")
        
    # Limpiamos nombres para evitar discrepancias por tildes o puntuación
    h = clean_text(str(home_name))
    a = clean_text(str(away_name))
    
    unique_str = f"MATCH_{date_str}_{h}_{a}"
    return _generate_uuid(unique_str)

def create_competition_id(comp_name: str) -> str:
    """Crea un ID único para la competición."""
    clean_comp = clean_text(comp_name)
    unique_str = f"COMP_{clean_comp}"
    return _generate_uuid(unique_str)

def create_team_id(team_name: str) -> str:
    """Crea un ID único para el equipo basado en su nombre limpio."""
    clean_team = clean_text(team_name)
    unique_str = f"TEAM_{clean_team}"
    return _generate_uuid(unique_str)

def create_player_id(player_name: str) -> str:
    """Crea un ID único para el jugador basado en su nombre normalizado."""
    # Los nombres de jugadores suelen ser los más problemáticos con tildes y comas
    clean_player = clean_text(player_name)
    unique_str = f"PLAYER_{clean_player}"
    return _generate_uuid(unique_str)


def write_to_s3_parquet(df, prefix, entity_name, pk_columns=None, upsert=True):
    """
    Writes a DataFrame to S3 as a single Parquet file.
    If upsert=True, it merges with existing data. If False, it overwrites.
    Returns: Final count of records saved.
    """
    import pandas as pd
    from src.config import S3_BUCKET_NAME, get_logger

    logger = get_logger()

    if not S3_BUCKET_NAME:
        logger.warning(f"Skipping upload for {entity_name}: S3_BUCKET_NAME is not set.")
        return 0
        
    if df.empty:
        logger.warning(f"Skipping upload for {entity_name}: DataFrame is empty.")
        return 0

    s3_path = f"s3://{S3_BUCKET_NAME}/{prefix}/{entity_name}/data.parquet"
    
    # 1. Attempt to load existing data for Upsert
    if upsert:
        try:
            existing_df = pd.read_parquet(s3_path, engine='pyarrow')
            df = pd.concat([existing_df, df], ignore_index=True)
            logger.info(f"Loaded existing data for {entity_name} from S3 for upsert.")
        except Exception:
            # File doesn't exist, proceed with current df
            logger.info(f"No existing data found for {entity_name} in S3, creating new file.")
            pass

    # 2. Cleanup of duplicates before writing
    if pk_columns:
        df = df.drop_duplicates(subset=pk_columns, keep='last')
        
    try:
        df.to_parquet(s3_path, index=False, engine='pyarrow')
        logger.info(f"Successfully uploaded {entity_name} to {s3_path} ({len(df)} records).")
        return len(df)
    except Exception as e:
        logger.error(f"CRITICAL ERROR: Failed to upload {entity_name} to S3: {e}")
        raise