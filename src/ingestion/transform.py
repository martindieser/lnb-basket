"""
Transformaciones en memoria de la Capa Bronze.
Funciones puras para preparar los payloads antes de persistir en S3.
"""
from typing import Dict, Tuple, Any

def partition_matches(matches_dict: Dict[str, Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """
    Separa el diccionario de partidos en dos particiones:
    - upcoming: partidos por disputarse ('No comenzado')
    - finished: partidos finalizados ('Terminado')
    """
    if not matches_dict:
        return {}, {}
        
    upcoming = {k: v for k, v in matches_dict.items() if v.get("Estado") == "No comenzado"}
    finished = {k: v for k, v in matches_dict.items() if v.get("Estado") == "Terminado"}
    return upcoming, finished

def create_upcoming_payload(game: Dict[str, Any]) -> Dict[str, Any]:
    """
    Genera la estructura JSON sintética para partidos futuros/no comenzados.
    Permite a la capa Silver registrar el fixture sin eventos de play-by-play.
    """
    id_local = game.get("IdEquipoLocal", "")
    id_visitante = game.get("IdEquipoVisitante", "")

    return {
        "resultado": "correcto",
        "partido": {
            "tipo_acta": "ESTADÍSTICAS",
            "estado_partido": "NO_COMENZADO",
            "local": game.get("NombreEquipoLocal", ""),
            "visitante": game.get("NombreEquipoVisitante", ""),
            "idlocal": id_local,
            "idvisitante": id_visitante,
            "tanteo_local": 0,
            "tanteo_visitante": 0,
            "numperiodos": 4,
            "tiempo_total_partido": 2400,
        },
        "envivo": {
            "jugadoresenpistalocal": [],
            "jugadoresenpistavisitante": [],
            "historialacciones": [],
        },
        "error": ""
    }
