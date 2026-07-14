import os
from dotenv import load_dotenv
from pathlib import Path
import logging
        
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

# Base paths with environment variable support for flexibility (Docker/Local)
DATA_DIR = os.getenv("DATA_DIR", "./data")
CABB_PATH = os.getenv("CABB_PATH", DATA_DIR)

# S3 Configuration
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_RAW_PREFIX = os.getenv("S3_RAW_PREFIX", "raw")
S3_CURATED_PREFIX = os.getenv("S3_CURATED_PREFIX", "curated")
S3_ANALYTICS_PREFIX = os.getenv("S3_ANALYTICS_PREFIX", "analytics")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


# Proxy Configuration
SCRAPER_PROXY = os.getenv("SCRAPER_PROXY")
PROXY_CA = os.getenv("PROXY_CA")


# Data Fixes and Mappings
UNKNOWN_NAME_FIX = {
    326138: 'AALIYA, LEE ABRAHAM', 325183: 'NEGRETE, ALEX',
    328501: 'GUERRA, LUCIANO MARTIN', 220857: 'LUGARINI, BAUTISTA',
    271232 : 'POMOLI LARRABURU, NICOLA', 329723: 'HOLT, EMMITT DWIGHT',
    96269 : 'CAPELLI, SANTIAGO', 323785 : 'ALLENDE, TOMAS DANIEL',
    328777 : 'HERNANDEZ, MANUEL ALONSO', 324076 : 'DOMINICI, LUCIO',
    174733 : 'GENNERO, AUGUSTO', 330818 : 'BEDNAREK, IGNACIO NICOLAS',
    323604: 'GOMEZ, MANUEL ALEJANDRO', 323618: 'DUPUY, EZEQUIEL MARIO',
    181021: 'SLIDER, JONATAN', 277487 : 'FERNANDEZ, VICTOR LUIS',
    325397 : 'PINEDA, DAMIAN', 325394 : 'ANDUJAR, LUCAS',
    211114 : 'MARIN, ANIBAL FEDERICO JUAN', 327737 : 'KRAMER, KELBY JOHN',
    327540 : 'THOMAS JR, MARCUS WILEY', 326666 : 'TIMOTHY BOND JR',
    93423 : 'BEDNAREK, IGNACIO', 326069: 'YAW OBENG MENSAH',
    231473 : 'BARROS, AGUSTIN', 322874 : 'CAUMO, JOAQUIN',
    326636 : 'DEVANTE WALLACE', 153017 : 'FERRI, VALENTINO'
}

TEAM_MAPPING = {
    # Add mappings if necessary
}


def get_logger(name=None):
    import logging
    import sys
    try:
        from prefect.logging import get_run_logger
        return get_run_logger()
    except Exception:
        # Si el root logger no tiene handlers, inicializamos basicConfig
        if not logging.getLogger().handlers:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
            )
        
        # Si no pasan name, inspeccionamos el frame para obtener el __name__ de quien llamó a get_logger
        if name is None:
            try:
                name = sys._getframe(1).f_globals.get('__name__', __name__)
            except Exception:
                name = __name__
                
        return logging.getLogger(name)