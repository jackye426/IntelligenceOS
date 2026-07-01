"""One-off script: look up 10 consultants in integrated_practitioners."""
import os, sys
import psycopg2, psycopg2.extras
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

# Prefer direct URL over pooler (pooler currently unreachable)
DB_URL = os.getenv('supabase_database_url') or os.getenv('SUPABASE_DATABASE_POOLER_URL', '')

NAMES = [
    ('Mr Chou-Phay Lim',      'Chou',      'Lim'),
    ('Miss Nadine Di Donato', 'Nadine',    'Di Donato'),
    ('Ms Uzma Ghaffar',       'Uzma',      'Ghaffar'),
    ('Mr Jonathan Pembridge', 'Jonathan',  'Pembridge'),
    ('Andy Pickersgill',      'Andy',      'Pickersgill'),
    ('Mohamed Elsherbiny',    'Mohamed',   'Elsherbiny'),
    ('Miss Donna Ghosh',      'Donna',     'Ghosh'),
    ('Ms Natalia Price',      'Natalia',   'Price'),
    ('Ms Joanna Street',      'Joanna',    'Street'),
    ('Mr Angus Thomson',      'Angus',     'Thomson'),
]

conn = psycopg2.connect(DB_URL, connect_timeout=15)
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

SELECT = "SELECT name, email, emails, email_confidence, email_manually_verified FROM integrated_practitioners "

for display, first, last in NAMES:
    rows = []

    # 1. exact last name
    cur.execute(SELECT + "WHERE LOWER(last_name) = LOWER(%s) LIMIT 5", (last,))
    rows = cur.fetchall()

    # 2. partial last name (handles "Di Donato" stored differently)
    if not rows:
        cur.execute(SELECT + "WHERE last_name ILIKE %s LIMIT 5", (f'%{last}%',))
        rows = cur.fetchall()

    # 3. first + partial last
    if not rows:
        cur.execute(
            SELECT + "WHERE first_name ILIKE %s AND last_name ILIKE %s LIMIT 5",
            (f'%{first}%', f'%{last.split()[-1]}%'),
        )
        rows = cur.fetchall()

    if rows:
        for r in rows:
            emails = r.get('emails') or []
            all_e = ([r['email']] if r.get('email') else []) + (emails if isinstance(emails, list) else [])
            print(f"  FOUND  {display}")
            print(f"         DB name : {r['name']}")
            print(f"         emails  : {all_e}")
            print(f"         verified: {r.get('email_manually_verified')}")
    else:
        print(f"  NOT FOUND  {display}")

conn.close()
