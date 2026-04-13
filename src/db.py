import sqlite3
import sys
import os

def run_sql(sql_file, db_file):
    if not os.path.exists(sql_file):
        raise FileNotFoundError(f"SQL file not found: {sql_file}")

    with open(sql_file, "r", encoding="utf-8") as f:
        sql_script = f.read()

    conn = sqlite3.connect(db_file)
    try:
        # Enable foreign key constraints
        conn.execute("PRAGMA foreign_keys = ON;")

        # Execute all SQL statements in the file
        conn.executescript(sql_script)

        conn.commit()
        print(f"✔ SQL executed successfully: {sql_file}")
        print(f"✔ Database file: {db_file}")
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python run_sqlite_sql.py file.sql [database.db]")
        sys.exit(1)

    sql_file = sys.argv[1]
    db_file = sys.argv[2] if len(sys.argv) > 2 else "database.db"

    run_sql(sql_file, db_file)
