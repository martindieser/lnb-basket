PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS competitions (
    id_comp TEXT PRIMARY KEY ,
    comp_name TEXT NOT NULL,
    start_date DATE,
    end_date DATE
);

CREATE TABLE IF NOT EXISTS teams (
	team_id TEXT PRIMARY KEY,
    team_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS players (
    player_id TEXT PRIMARY KEY,
    player_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY ,
    id_comp TEXT NOT NULL,
    home_id TEXT NOT NULL,
    away_id TEXT NOT NULL,
    date TIMESTAMP NOT NULL,
    status TEXT NOT NULL,
    home_pts INTEGER,
    away_pts INTEGER,
    periods INTEGER,
    total_duration_mm INTEGER,
    extra_duration_mm INTEGER,
    UNIQUE (id_comp, home_id, away_id, date),
    FOREIGN KEY (id_comp) REFERENCES competitions (id_comp),
    FOREIGN KEY (home_id) REFERENCES teams (team_id),
    FOREIGN KEY (away_id) REFERENCES teams (team_id)
);

CREATE TABLE IF NOT EXISTS pbps (
    pbp_id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL,
    match_id TEXT NOT NULL,
    team_id TEXT,
    player_id TEXT,  
    period INTEGER NOT NULL,
    clk TEXT NOT NULL,
    event_type TEXT NOT NULL,
    x REAL,
    y REAL,
    jersey INTEGER,
    zone TEXT,
    note TEXT,
    FOREIGN KEY (match_id) REFERENCES matches (match_id),
    FOREIGN KEY (team_id) REFERENCES teams (team_id),
    FOREIGN KEY (player_id) REFERENCES players (player_id)
);



CREATE TABLE odds_history (
    id TEXT PRIMARY KEY,             -- UUID preferred
    match_id TEXT NOT NULL,          -- Foreign key to matches table
    provider TEXT NOT NULL,          -- e.g., 'aiscore'
    market TEXT NOT NULL,            -- 'handicap', 'over_under', '1x2'
    
    -- Odds Details
    label TEXT NOT NULL,             -- 'home', 'away', 'over', 'under', 'draw'
    line REAL,                       -- Nullable (e.g., -3.5). NULL for Moneyline/1x2
    price REAL NOT NULL,             -- Decimal odds (e.g., 1.90)
    
    -- Context (Crucial for Analysis)
    period TEXT,                     -- e.g., '1Q', '2H', 'FT' (Time context)
    score TEXT,                      -- e.g., '1-0', '62-68' (Score context)
    is_live BOOLEAN DEFAULT 0,       -- Helps filter pre-match vs in-play easily
    
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- IMPORTANT: Add Indexes for Speed
CREATE INDEX idx_odds_match ON odds_history(match_id);
CREATE INDEX idx_odds_lookup ON odds_history(match_id, market, provider);