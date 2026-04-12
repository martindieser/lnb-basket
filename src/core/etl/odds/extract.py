import json
from pathlib import Path

def extract_specific_structure(root_directory):
    """
    Recorre una estructura donde:
    - Matches: root/provider/matches/*.json
    - Odds:    root/provider/odds/{match_id}/{timestamp}.json
    """
    raw_payload = {
        'matches': [],
        'odds': []
    }
    
    root_path = Path(root_directory)
    
    if not root_path.exists():
        print(f"Directorio no encontrado: {root_directory}")
        return raw_payload

    # Buscamos recursivamente TODOS los json
    for file_path in root_path.rglob('*.json'):
        
        # 'parts' nos da una tupla con cada trozo de la ruta
        # Ej: ('data', 'pinnacle', 'odds', '123456', '2023-10-25.json')
        parts = file_path.parts
        
        # --- LÓGICA PARA ODDS (Estructura Profunda) ---
        if 'odds' in parts:
            # Estructura esperada: .../provider/odds/match_id/timestamp.json
            try:
                # file_path.parent es la carpeta del ID (ej: 123456)
                match_id = file_path.parent.name
                
                # file_path.parent.parent es la carpeta 'odds'
                # file_path.parent.parent.parent es el proveedor (ej: pinnacle)
                provider = file_path.parent.parent.parent.name
                
                content = _load_json(file_path)
                if content:
                    raw_payload['odds'].append({
                        'metadata': {
                            'provider': provider,
                            'match_id': match_id,   # ¡Clave! Sacado del nombre de la carpeta
                            'timestamp_file': file_path.stem # El nombre del archivo sin .json
                        },
                        'data': content
                    })
            except IndexError:
                print(f"Ruta de odds con estructura extraña: {file_path}")

        # --- LÓGICA PARA MATCHES (Estructura Plana) ---
        elif 'matches' in parts:
            # Estructura esperada: .../provider/matches/archivo.json
            try:
                # Aquí el padre directo SI es la categoría 'matches'
                # El abuelo es el proveedor
                provider = file_path.parent.parent.name
                
                content = _load_json(file_path)
                if content:
                    raw_payload['matches'].append({
                        'metadata': {
                            'provider': provider,
                            'filename': file_path.name
                        },
                        'data': content
                    })
            except IndexError:
                print(f"Ruta de matches extraña: {file_path}")

    return raw_payload

def _load_json(path):
    try:
        with path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None