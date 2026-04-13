# from . import CABB_PATH
import json
import os
import re
import time
from config import CABB_PATH



class Cache:
    """
    we have the ids, the problem is that they hash internals ids for each user,
    so we have to make our own internal match id and assign a period for each existing profile in the scraper then to 
    fetch ids we can do a prefetching phase
    """
    profiles_folder = os.path.join(os.path.join(CABB_PATH, 'config'), 'profiles')

    @staticmethod
    def create_internal_league_id(sport, league_name):
        clean_league = re.sub(r'[^a-z0-9]', '', league_name.lower())
        clean_sport = re.sub(r'[^a-z0-9]', '', sport.lower())
        return f"{clean_league}_{clean_sport}"
        
    @staticmethod
    def create_internal_match_id(league, sport, home, away, date_obj):
        """
        Creates ID: league_home_vs_away_YYYYMMDDHHMM
        """
        clean_league = Cache.create_internal_league_id(sport, league)
        clean_home = re.sub(r'[^a-z0-9]', '', home.lower())
        clean_away = re.sub(r'[^a-z0-9]', '', away.lower())
        
        # UPDATED: Now includes Hour and Minute (%H%M)
        # Example: 202410072210
        clean_date = date_obj.strftime("%Y%m%d%H%M")
        
        return f"{clean_league}_{clean_home}_vs_{clean_away}_{clean_date}"
    
    @staticmethod
    def available_profiles():
        if not os.path.exists(Cache.profiles_folder):
            return []

        ids = []
        for filename in os.listdir(Cache.profiles_folder):
            if filename.endswith(".json"):
                clean_id = filename.replace(".json", "")
                ids.append(clean_id)
        
        return ids

    def __init__(self, profile_id, initial_auth=None):

        os.makedirs(Cache.profiles_folder, exist_ok=True)
        self.file_path = os.path.join(Cache.profiles_folder, f'{str(profile_id)}.json')

        if profile_id not in Cache.available_profiles():
            
            if initial_auth is None or not all(k in initial_auth for k in ('id_dispositivo', 'key')):
                raise ValueError('Auth data (id_dispositivo, key) is necessary to create a new profile')

            # new profile_id so we create it
            self.state = { 
                "id_dispositivo": initial_auth['id_dispositivo'], 
                "key": initial_auth['key'], 
                "log": [],
                "matches": {}, 
                "leagues": {},
            }

            self.write() 
        else:
            self.state = {}
            with open(self.file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.state["id_dispositivo"] = data.get("id_dispositivo")
                self.state["key"] = data.get("key")
                self.state["log"] = data.get("log")
                self.state["matches"] = data.get("matches")
                self.state["leagues"] = data.get("leagues")

    def write(self):
        with open(self.file_path, 'w+') as f:
            json.dump(self.state, f, indent=4)

    def update_device(self, key):
        # self.state['id_dispositivo'] = id_dispositivo
        self.state['key'] = key 
        self.write()

    def add_log(self, endpoint):
        self.state['log'].append({
            "timestamp": time.time(),
            "endpoint": endpoint
        })
        self.write()
    
    def register_match(self, internal_id, external_hashed_id):
        if internal_id not in self.state["matches"]:
            self.state["matches"][internal_id] = {}
        
        self.state["matches"][internal_id] = external_hashed_id
        self.write()

    def register_league(self, internal_id, external_hashed_id):
        if internal_id not in self.state["leagues"]:
            self.state["leagues"][internal_id] = {}
            
        self.state["leagues"][internal_id] = external_hashed_id
        self.write()

    def get_hashed_id(self, internal_id, type='match'):
        cat = "leagues" if type == 'league' else "matches"
        return self.state[cat].get(internal_id, {})