import sqlite3

def load_odds_into_db(normalized_odds, db_path):
    """
    Carga un lote de cuotas (odds) en la base de datos SQLite.
    
    Estrategia: 'Staging Table' (Tabla Temporal).
    1. Vuelca los datos crudos a una tabla temporal.
    2. Ejecuta una query compleja que cruza la temporal con la histórica.
    3. Solo inserta en 'odds_history' si el ID no existe Y el precio ha cambiado.
    """
    if not normalized_odds:
        return

    # isolation_level=None permite gestionar las transacciones manualmente (BEGIN/COMMIT)
    with sqlite3.connect(db_path, isolation_level=None) as conn:
        cursor = conn.cursor()
        
        try:
            # Iniciamos la transacción segura
            cursor.execute("BEGIN TRANSACTION;")

            # ---------------------------------------------------------
            # PASO 1: Crear Tabla Temporal (Staging)
            # ---------------------------------------------------------
            # Esta tabla vive solo en memoria/disco durante esta conexión.
            cursor.execute("DROP TABLE IF EXISTS odds_staging")
            cursor.execute("""
                CREATE TEMPORARY TABLE odds_staging (
                    id TEXT,
                    match_id TEXT,
                    provider TEXT,
                    market TEXT,
                    line TEXT,
                    label TEXT,
                    price REAL,
                    score TEXT,
                    recorded_at TEXT
                )
            """)

            # ---------------------------------------------------------
            # PASO 2: Volcado Masivo (Raw Insert)
            # ---------------------------------------------------------
            # Preparamos los datos. Es mucho más rápido insertar tuplas que diccionarios.
            data_tuples = [
                (o['id'], o['match_id'], o['provider'], o['market'], o['line'],
                 o['label'], o['price'], o['score'], o['recorded_at'])
                for o in normalized_odds
            ]
            
            cursor.executemany("""
                INSERT INTO odds_staging (id, match_id, provider, market, line, label, price, score, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, data_tuples)

            # ---------------------------------------------------------
            # PASO 3: Inserción Inteligente (SQL Logic)
            # ---------------------------------------------------------
            # Aquí ocurre la magia:
            # - LEFT JOIN: Filtra IDs que ya existen (evita PK errors).
            # - Subquery: Compara el precio con el último registro de esa misma línea.
            
            sql_merge = """
                INSERT INTO odds_history (id, match_id, provider, market, line, label, price, score, recorded_at)
                SELECT 
                    s.id, s.match_id, s.provider, s.market, s.line, s.label, s.price, s.score, s.recorded_at
                FROM odds_staging s
                -- FILTRO DE DUPLICADOS (Idempotencia):
                -- Si el ID ya existe en la tabla final, h.id no será NULL y descartamos la fila.
                LEFT JOIN odds_history h ON s.id = h.id
                WHERE h.id IS NULL 
                AND (
                    -- LOGICA DE CAMBIO DE PRECIO:
                    -- Buscamos el último precio para este mercado/línea/label
                    s.price != (
                        SELECT price 
                        FROM odds_history hist
                        WHERE hist.match_id = s.match_id 
                          AND hist.provider = s.provider 
                          AND hist.market = s.market 
                          AND (hist.line = s.line OR (hist.line IS NULL AND s.line IS NULL))
                          AND hist.label = s.label
                        ORDER BY hist.id DESC 
                        LIMIT 1
                    )
                    OR 
                    -- Si la subconsulta devuelve NULL (es la primera vez que vemos esta línea), insertamos.
                    (
                        SELECT price 
                        FROM odds_history hist
                        WHERE hist.match_id = s.match_id 
                          AND hist.provider = s.provider 
                          AND hist.market = s.market 
                          AND (hist.line = s.line OR (hist.line IS NULL AND s.line IS NULL))
                          AND hist.label = s.label
                        LIMIT 1
                    ) IS NULL
                );
            """
            
            cursor.execute(sql_merge)
            rows_inserted = cursor.rowcount
            
            # Limpiamos la tabla temporal (opcional, se borra sola al cerrar, pero ahorra memoria)
            cursor.execute("DROP TABLE IF EXISTS odds_staging")
            
            cursor.execute("COMMIT;")
            print(f"✅ DB Update: {rows_inserted} nuevas cuotas insertadas.")

        except Exception as e:
            cursor.execute("ROLLBACK;")
            print(f"❌ Error crítico en DB: {e}")
            raise e