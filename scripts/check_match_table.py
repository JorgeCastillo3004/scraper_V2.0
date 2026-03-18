import psycopg2
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS


def get_connection():
    return psycopg2.connect(host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS)


def print_status():
    con = get_connection()
    cur = con.cursor()
    cur.execute("SELECT status, COUNT(*) FROM match GROUP BY status ORDER BY COUNT(*) DESC;")
    rows = cur.fetchall()
    print("\n── Estado actual de match.status ──────────────────────")
    for status, count in rows:
        print(f"  {str(status):<20} {count:>6} partidos")
    print()
    cur.close()
    con.close()


# Mapa de valores legacy → valor correcto (según schema SQL)
STATUS_MIGRATION = {
    'completed':  'COMPLETED',
    'schedule':  'SCHEDULED',
    'R':          'COMPLETED',
    'P':          'SCHEDULED',
}


def migrate_status(dry_run: bool = False):
    con = get_connection()
    cur = con.cursor()

    total_updated = 0
    for old_val, new_val in STATUS_MIGRATION.items():
        cur.execute("SELECT COUNT(*) FROM match WHERE status = %s", (old_val,))
        count = cur.fetchone()[0]
        if count == 0:
            print(f"  [SKIP] '{old_val}' → '{new_val}'  (0 registros)")
            continue

        if dry_run:
            print(f"  [DRY ] '{old_val}' → '{new_val}'  ({count} registros)")
        else:
            cur.execute("UPDATE match SET status = %s WHERE status = %s", (new_val, old_val))
            print(f"  [OK  ] '{old_val}' → '{new_val}'  ({count} registros actualizados)")
            total_updated += count

    if not dry_run:
        con.commit()
        print(f"\n  Total actualizado: {total_updated} registros")
    else:
        print("\n  Dry-run completado. Ejecuta con --run para aplicar los cambios.")

    cur.close()
    con.close()


if __name__ == "__main__":
    dry_run = "--run" not in sys.argv

    print_status()

    print("── Migración de status ─────────────────────────────────")
    migrate_status(dry_run=dry_run)

    if not dry_run:
        print("\n── Estado final ────────────────────────────────────────")
        print_status()
