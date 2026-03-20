"""
check_match_status.py
=====================
Diagnóstico y corrección del campo `status` en la tabla `match` de la base de datos.

DESCRIPCIÓN
-----------
El scraper asigna uno de estos valores al campo `status` de cada partido:

    COMPLETED   → Partido terminado (sección results, match_status='Finished')
    SCHEDULED   → Partido pendiente / sin resultado aún (sección fixtures)
    in progress → Partido en curso (actualizado por el script live)

Con versiones anteriores del código se usaban valores en minúsculas o abreviados
('completed', 'schedule', 'R', 'P'). Este script detecta y corrige esos valores legacy.

MAPA DE MIGRACIÓN
-----------------
    'completed'  →  'COMPLETED'
    'schedule'   →  'SCHEDULED'
    'R'          →  'COMPLETED'   (legacy: result/finished)
    'P'          →  'SCHEDULED'   (legacy: pending)

USO
---
    # Ver estado actual de la tabla (sin modificar nada):
    python scripts/check_match_status.py

    # Simular la migración (dry-run, sin aplicar cambios):
    python scripts/check_match_status.py

    # Aplicar la migración en la base de datos:
    python scripts/check_match_status.py --run

SALIDA ESPERADA
---------------
    ── Estado actual de match.status ──────────────────────
      COMPLETED            12540 partidos
      SCHEDULED             3210 partidos
      completed              870 partidos   ← legacy, se corregirá con --run

    ── Migración de status ─────────────────────────────────
      [DRY ] 'completed' → 'COMPLETED'  (870 registros)
      [SKIP] 'schedule'  → 'SCHEDULED'  (0 registros)
      ...
    Dry-run completado. Ejecuta con --run para aplicar los cambios.

NOTAS
-----
- Requiere config.py con DB_HOST, DB_NAME, DB_USER, DB_PASS.
- Sin --run el script solo muestra lo que haría (modo dry-run por defecto).
- Ejecutar --run es seguro: solo actualiza registros con valores legacy.
- Luego de una migración muestra el estado final de la tabla.
"""

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
