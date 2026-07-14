from typing import List, Dict, Optional
from curl_cffi import requests
from src.config import get_logger
from bs4 import BeautifulSoup
import re
import datetime

PLAYER_ID_RE = re.compile(r"/jugador/(\d+)/")
logger = get_logger()

class ProballersScraper:
    """
    Scraper to search and extract player details (height, nationality, birth date)
    from Proballers.com.
    """
    BASE_URL = "https://www.proballers.com"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    def __init__(self, proxy: Optional[str] = None, cf_clearance: Optional[str] = None):
        self.session = requests.Session()
        self.proxy = proxy
        self.cf_clearance = cf_clearance
        if self.proxy:
            self.session.proxies.update({'http': self.proxy, 'https': self.proxy})
           
        headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'accept-language': 'es-ES,es;q=0.9',
            'cache-control': 'no-cache',
            'pragma': 'no-cache',
            'priority': 'u=0, i',
            'referer': 'https://www.proballers.com/es/baloncesto/liga/188/argentina-liga-a/jugadores/2024?__cf_chl_tk=AEP8t7PSFqnie6HYqieI6hct3MMuiuilq_j7waM.ASE-1783988957-1.0.1.1-shsIfyFeACXaIYcF0tCfEfG0W8GTwL8x2rU_IdU.PvU',
            'sec-ch-ua': '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
            'sec-ch-ua-arch': '"x86"',
            'sec-ch-ua-bitness': '"64"',
            'sec-ch-ua-full-version': '"150.0.7871.101"',
            'sec-ch-ua-full-version-list': '"Not;A=Brand";v="8.0.0.0", "Chromium";v="150.0.7871.101", "Google Chrome";v="150.0.7871.101"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-model': '""',
            'sec-ch-ua-platform': '"Windows"',
            'sec-ch-ua-platform-version': '"10.0.0"',
            'sec-fetch-dest': 'document',
            'sec-fetch-mode': 'navigate',
            'sec-fetch-site': 'same-origin',
            'sec-fetch-user': '?1',
            'upgrade-insecure-requests': '1',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
        }
     
        self.session.headers.update(headers)

    def parse_height(self, raw: str):
        """'2m05' -> 205, '1m85' -> 185, '-' o '' -> None"""
        raw = raw.strip()
        match = re.match(r"(\d+)m(\d+)", raw)
        if not match:
            return None
        meters, cm = match.groups()
        return int(meters) * 100 + int(cm)


    def estimate_birth_date_from_age(self, age: int) -> str:
        """
        Estimates a birth date (YYYY-01-01) from an age to avoid saving a transient age
        value that changes over time.
        """
        try:
            current_year = datetime.datetime.now().year
            birth_year = current_year - int(age)
            return f"{birth_year}-01-01"
        except Exception as e:
            logger.warning(f"Could not estimate birth date from age '{age}': {e}")
            return None

    def parse_age(self, raw: str):
        """'21' -> 21, '' -> None"""
        raw = raw.strip()
        return int(raw) if raw.isdigit() else None
     
     
    def parse_nationality(self, raw: str):
        """'Argentina, Italy' -> 'Argentina, Italy'; '' -> None"""
        raw = raw.strip()
        return raw if raw else None
     
     
    def extract_players(self, html: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        result = {}
     
        for row in soup.select("table.table tbody tr"):
            cells = row.find_all("td")
            if len(cells) < 5:
                continue
     
            link = cells[0].find("a", class_="list-player-entry")
            if not link or not link.get("href"):
                continue
     
            match = PLAYER_ID_RE.search(link["href"])
            if not match:
                continue
            player_id = match.group(1)
     
            name = link.get_text(" ", strip=True)
            name = re.sub(r"\s+", " ", name)
            age_raw = cells[2].get_text(strip=True)
            height_raw = cells[3].get_text(strip=True)
            nationality_raw = cells[4].get_text(strip=True)
     
            result[player_id] = {
                "name": name,
                "height_cm": self.parse_height(height_raw),
                "nationality": self.parse_nationality(nationality_raw),
                "birth_date": self.estimate_birth_date_from_age( self.parse_age(age_raw) )
            }
     
        return result




    def scrape_season_players(self, season: str) -> Dict[str, Dict]:
        """
        Scrapes all player details for a given season.
        """
        logger.info(f"Scraping players for season: {season}")
        cookies = {
            '__qca': 'I0-1718313252-1783975703659',
            '_ga': 'GA1.1.266068320.1783974192',
            '_li_dcdm_c': '.proballers.com',
            '_lc2_fpi': '3f0c2a22ae92--01kxejbwqfpk4pbt9vfypzdv4d',
            '_lc2_fpi_meta': '%7B%22w%22%3A1783974195951%7D',
            '_sharedid': 'bd7a3533-df8e-4608-997d-1fd1dbe2742c',
            'amxId': 'amx*3*c3910659-7c33-40e5-94c7-d8f2466b3b8c*1a9167598444120ef5c888859c8f3958',
            'pbjs_li_nonid': '%7B%7D',
            '_sharedid_cst': 'kSylLAssaw%3D%3D',
            'pbjs_li_nonid_cst': 'kSylLAssaw%3D%3D',
            'amxId_cst': 'kSylLAssaw%3D%3D',
            '__gads': 'ID=b54b886d57d08b7a:T=1783974197:RT=1783988808:S=ALNI_MY7WzZojDFQCPeDTtHalhZy6y9rsw',
            '__gpi': 'UID=00001437cbb21652:T=1783974197:RT=1783988808:S=ALNI_MaOSddL8ayoQNykMW4LyhBw92JTqA',
            '__eoi': 'ID=8873c531749ed18f:T=1783974197:RT=1783988808:S=AA-Afjb7sClIelOfeugZD4rtG8Rg',
            'cf_clearance': self.cf_clearance,
            '_ga_7DQG2G1WK9': 'GS2.1.s1783988808$o4$g1$t1783988963$j53$l0$h0',
            'cto_bidid': 'JcUcF9tS0glMkZXMmtBclIzZU5SN0ZJN25TejBkdW84UU8yZVZIMWdTZHVKZHlhbm9aeiUyQlUwWDBVeVU3JTJGblRFYXA5aktvZiUyRlFjMlFQV2lYSjFBOHBFVFZQbmdSVCUyRnRFZ21wQlNNZ3dxNWxhb2RlYjB1clFqRnpJenJoSDMzU1BGamQ3ZTk',
            'cto_bundle': 'XAI_Tl9oT3BlNzl5MjRqOVdKOE9lMmE2MzFjSmZ1NXFTS2dQRUhlaU93ZUg1bnkwOFpYaVBEQiUyRnJYUmJpRjRQZW05WkNPbHBXb29KTVBlSVBwcU9DTmdBajFhYU5qSEl2dHcxQTY1d3d4SjcxWG15dUhBempBVklGdyUyQlFiYW9VZ04lMkIlMkZFZnZFNmVyZ1RncHhMQ0ZiMEFSZHdqdyUzRCUzRA',
        }

        response = self.session.get(
            f"https://www.proballers.com/es/baloncesto/liga/188/argentina-liga-a/jugadores/{season}",
            cookies=cookies)
        response.raise_for_status()
        players = self.extract_players(response.text)
        logger.info(players)
        # { "player_id": { "height_cm": 203, "nationality": "Argentina", "birth_date": "2001-01-31" } }
        return players

def extract_player_details(seasons: List[str], cf_clearance: Optional[str] = None) -> Dict[str, Dict]:
    """
    Orchestrates the extraction of player details for a list of seasons.
    """
    scraper = ProballersScraper(cf_clearance=cf_clearance)
    all_player_details = {}
    
    for season in seasons:
        logger.info(f"Starting extraction for season: {season}")
        season_details = scraper.scrape_season_players(season)
        all_player_details.update(season_details)
        
    logger.info(f"Extracted details for {len(all_player_details)} unique players across all seasons.")
    return all_player_details
