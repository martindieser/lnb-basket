import json
from datetime import datetime
from zoneinfo import ZoneInfo
from ...config import TEAM_MAPPING
from ..utils import create_match_id, create_outcome_id, clean_team_name

# --- PINNACLE LOGIC ---

def pinnacle_odds_to_outcomes(raw_odds_list, current_time=None):
    """
    Parses the new Pinnacle 'data' list containing markets and prices.
    """
    flat_rows = []
    
    # Mapping Pinnacle API types to your internal schema
    market_map = {
        'spread': 'handicap',
        'total': 'over_under',
        'moneyline': 'moneyline' 
    }
    
    if current_time is None:
        current_time = datetime.utcnow()

    # raw_odds_list is the list inside ['data']
    for item in raw_odds_list:
        pinnacle_type = item.get('type')
        market_type = market_map.get(pinnacle_type)
        
        # Skip if market is unknown or has no prices
        if not market_type or 'prices' not in item:
            continue

        period = item.get('period')

        for price_obj in item['prices']:
            price_raw = price_obj.get('price')
            
            if price_raw is None:
                continue

            # Convert American Odds to Decimal
            if price_raw > 0:
                decimal_price = (price_raw / 100.0) + 1.0
            else:
                decimal_price = (100.0 / abs(price_raw)) + 1.0

            # Get the line value (spread/total points)
            line_val = price_obj.get('points') 

            row = {
                'market': market_type,
                'line': line_val,
                'label': price_obj.get('designation'), # home, away, over, under
                'price': round(decimal_price, 3),
                'provider': 'pinnacle',
                'period': period,
                'score': None, # Pinnacle raw feed usually doesn't have live score in odds
                'recorded_at': current_time.strftime('%Y-%m-%d %H:%M:%S') 
            }
            
            row['id'] = create_outcome_id(row)
            flat_rows.append(row)
            
    return flat_rows


def standarize_matches_pinnacle(raw_match):
    """
    Standardizes Pinnacle match metadata.
    Handles ISO 8601 dates (e.g., 2026-01-07T00:00:00Z).
    """
    utc_str = raw_match.get('utc_date')
    
    try:
        # Handle 'Z' by replacing with +00:00 for strict ISO parsing
        utc_dt = datetime.fromisoformat(utc_str.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        # Fallback if format is different
        utc_dt = datetime.strptime(utc_str, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("UTC"))

    # Convert to Argentina time
    arg_dt = utc_dt.astimezone(ZoneInfo("America/Argentina/Buenos_Aires"))

    return {
        'home_team': raw_match.get('home_team'),
        'away_team': raw_match.get('away_team'),
        'date': arg_dt,
        'external_match_id': str(raw_match.get('matchup_id')),
    }


# --- MAIN ETL FUNCTIONS ---

def normalize_teams(raw_data):
    """
    Processes the 'matches' list from the JSON.
    Resolves team names using TEAM_MAPPING.
    """
    def get_resolved_name(team_name):
        if not team_name: return None
        clean_name = clean_team_name(team_name.strip().lower())
        return TEAM_MAPPING.get(clean_name)

    normalized_matches = []
    
    # Iterate over the new 'matches' list structure
    for item in raw_data.get('matches', []):
        
        # Check provider in metadata
        meta = item.get('metadata', {})
        provider = meta.get('provider') or item.get('provider')
        
        if provider != 'pinnacle':
            continue
        
        # Extract the actual match data
        match_data = item.get('data') or item
        
        match = standarize_matches_pinnacle(match_data)

        # Resolve Teams
        home_res = get_resolved_name(match.get('home_team'))
        away_res = get_resolved_name(match.get('away_team'))

        if home_res and away_res:
            new_match = match.copy()
            new_match['home_team'] = home_res
            new_match['away_team'] = away_res
            # Generate internal match ID
            new_match['match_id'] = create_match_id(
                home_res, 
                away_res, 
                new_match['date'].strftime('%Y%m%d')
            )
            normalized_matches.append(new_match)
        else:
            # Optional: Log missing mappings
            # home = clean_team_name(match.get('home_team'))
            # away = clean_team_name(match.get('away_team'))
            # print(f"Skipping match (mapping not found): {home} vs {away}")
            pass
                
    return normalized_matches


def normalize_odds(raw_data, normalized_matches):
    """
    Processes the 'odds' list from the JSON.
    Links odds to matches using external_match_id.
    """
    # Create quick lookup: external_id -> internal_id
    match_lookup = {
        m['external_match_id']: m['match_id'] 
        for m in normalized_matches
    }
    
    seen_ids = set()      
    normalized_odds = []
    
    current_time = datetime.utcnow()

    # Iterate over the new 'odds' list structure
    for item in raw_data.get('odds', []):
        
        meta = item.get('metadata', {})
        provider = meta.get('provider') or item.get('provider')
        
        if provider != 'pinnacle':
            continue

        # Get the external Match ID from metadata (preferred) or filename
        if 'match_id' in meta:
            external_match_id = str(meta['match_id'])
        elif 'filename' in meta:
            # Fallback for old files: 1621841133.json -> 1621841133
            external_match_id = meta['filename'].split('.')[0].split('_')[0]
        else:
            continue

        # Skip if we don't have a resolved match for this ID
        if external_match_id not in match_lookup:
            continue
            
        internal_match_id = match_lookup[external_match_id]
        
        # The 'data' key contains the list of markets
        odds_data_list = item.get('data', [])
        
        # Parse the odds
        parsed_outcomes = pinnacle_odds_to_outcomes(odds_data_list, current_time)

        for out in parsed_outcomes:
            out['match_id'] = internal_match_id
            outcome_id = out.get('id')
            
            # Deduplicate
            if outcome_id not in seen_ids:
                normalized_odds.append(out)
                seen_ids.add(outcome_id)

    return normalized_odds