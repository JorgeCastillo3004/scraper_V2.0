"""
_migrate_without_stats.py
-------------------------
Parsea logs/fix_null_*.log de hoy y marca como 'without_statistics' en DB
y en tmp/without_statistics.json todos los matches que ya fueron probados
y dieron [SKIP stats] no_stats_on_page o [SKIP stats] empty_stats.

Reconstruye el cache + actualiza DB en una sola pasada.

Uso:
    env_sports/bin/python scripts/_migrate_without_stats.py --apply
"""
import os, sys, re, json, argparse, glob
from datetime import datetime
from collections import defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import psycopg2
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
from fix_null_team_ids import (
    WITHOUT_STATS_PATH, load_without_stats_cache, mark_match_without_stats,
)


def parse_logs(logs_dir):
    """
    Recorre logs/fix_null_*.log de hoy. Identifica bloques de match
    (encabezado '>>> YYYY-MM-DD Name~Name') seguidos de '[SKIP stats]'.
    Retorna lista de (match_date, match_name, skip_reason).
    """
    pattern_match = re.compile(r'^\s*>>>\s+(\d{4}-\d{2}-\d{2})\s+(.+?)\s+needs=', re.MULTILINE)
    pattern_skip  = re.compile(r'\[SKIP stats\]\s+(\S+)')

    results = []
    log_files = sorted(glob.glob(os.path.join(logs_dir, 'fix_null_*.log')))
    print(f'Logs encontrados: {len(log_files)}')

    for log_path in log_files:
        try:
            with open(log_path, errors='replace') as f:
                txt = f.read()
        except Exception as e:
            print(f'  [WARN] no se pudo leer {log_path}: {e}')
            continue

        # Dividir por bloques de match
        positions = [m.start() for m in pattern_match.finditer(txt)]
        positions.append(len(txt))
        for i in range(len(positions) - 1):
            chunk = txt[positions[i]:positions[i+1]]
            m_hdr = pattern_match.search(chunk)
            if not m_hdr:
                continue
            m_date = m_hdr.group(1)
            m_name = m_hdr.group(2).strip()
            m_skip = pattern_skip.search(chunk)
            if m_skip:
                results.append((m_date, m_name, m_skip.group(1)))
    return results


def lookup_match_ids(cur, parsed):
    """De (date, name) → match_id en DB. Devuelve lista de tuplas."""
    out = []
    not_found = []
    for date_str, name, reason in parsed:
        cur.execute(
            "SELECT match_id FROM match WHERE match_date=%s AND name=%s",
            (date_str, name)
        )
        rows = cur.fetchall()
        if not rows:
            not_found.append((date_str, name))
            continue
        for r in rows:
            out.append((r[0], reason))
    return out, not_found


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply', action='store_true', help='Aplicar cambios (default: dry-run)')
    args = p.parse_args()

    logs_dir = os.path.join(ROOT, 'logs')
    parsed = parse_logs(logs_dir)
    print(f'Bloques [SKIP stats] detectados en logs: {len(parsed)}')

    if not parsed:
        print('Nada que migrar.')
        return

    # Distribucion de razones
    by_reason = defaultdict(int)
    for _, _, r in parsed:
        by_reason[r] += 1
    print('Por razon:')
    for r, n in sorted(by_reason.items(), key=lambda x: -x[1]):
        print(f'  {r}: {n}')

    # Filtrar razones legitimas de "sin cobertura": excluir errores temporales
    LEGIT_REASONS = {'no_stats_on_page', 'empty_stats'}
    parsed_legit = [p for p in parsed if p[2].rstrip(':') in LEGIT_REASONS]
    excluded = len(parsed) - len(parsed_legit)
    if excluded:
        print(f'(Filtrados {excluded} entries por razones temporales como extract_error)')

    # Mapear a match_ids
    conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = conn.cursor()
    pairs, not_found = lookup_match_ids(cur, parsed_legit)

    # Dedup: el mismo match_id puede aparecer en multiples logs
    unique = {}
    for mid, reason in pairs:
        unique[mid] = reason
    print(f'\nMatches únicos a marcar: {len(unique)} (logs tenían {len(pairs)} entries)')
    print(f'No encontrados en DB: {len(not_found)}')

    if not args.apply:
        print('\n[DRY-RUN] No se aplica nada. Re-ejecutar con --apply.')
        print('\nMuestra de matches a marcar (primeros 5):')
        for mid, reason in list(unique.items())[:5]:
            cur.execute("SELECT name, match_date FROM match WHERE match_id=%s", (mid,))
            r = cur.fetchone()
            print(f'  {mid[:8]} | {r[1]} | {r[0]!r} | reason={reason}')
        cur.close(); conn.close()
        return

    # APPLY
    updated_db = 0
    skipped_already_has_stats = 0
    cached_count = 0
    for mid, reason in unique.items():
        # 1) Cache JSON
        mark_match_without_stats(mid, reason=reason)
        cached_count += 1
        # 2) DB UPDATE (solo si statistic está vacío — no sobrescribe stats reales)
        cur.execute(
            """UPDATE match SET statistic = 'without_statistics'
               WHERE match_id = %s
                 AND (statistic IS NULL OR statistic IN ('', '{}'))""",
            (mid,)
        )
        if cur.rowcount > 0:
            updated_db += 1
        else:
            skipped_already_has_stats += 1
    conn.commit()
    cur.close(); conn.close()

    print(f'\n[APPLY] Resultado:')
    print(f'  Cache JSON entries:                {cached_count}')
    print(f'  DB UPDATE match.statistic:         {updated_db}')
    print(f'  Skipped (ya tenian stats reales):  {skipped_already_has_stats}')


if __name__ == '__main__':
    main()
