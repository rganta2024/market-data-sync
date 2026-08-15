import os
import psycopg2

def main():
    db_url = os.environ.get("HEDGE_DATABASE_URL")
    if not db_url:
        raise ValueError("HEDGE_DATABASE_URL environment variable is not set.")
        
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()

    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        sql = f.read()

    cur.execute(sql)
    print("SUCCESS: Database tables, indexes, and views created successfully!")

    cur.execute("""
        SELECT table_name, table_type 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        ORDER BY table_name;
    """)
    rows = cur.fetchall()
    print("\nPublic Schema Tables & Views:")
    for name, t_type in rows:
        print(f" - {name} ({t_type})")
        
    conn.close()

if __name__ == "__main__":
    main()
