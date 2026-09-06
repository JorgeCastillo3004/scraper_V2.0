#!/usr/bin/env python3
"""
_mon_live_driver_mem.py — UNA muestra del consumo del driver de LIVE.

Identifica el árbol del driver de Live (start_driver.py --label live → geckodriver
→ firefox --marionette + content procs) y suma PSS (memoria real, descuenta páginas
compartidas) y RSS. Imprime una línea CSV y la anexa a logs/_live_driver_mem.csv.
Lectura PSS vía /proc/<pid>/smaps_rollup. No mata ni toca nada (solo lee /proc).
"""
import os, sys, glob, time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CSV = os.path.join(ROOT, 'logs', '_live_driver_mem.csv')

def procs():
    out = {}
    for p in glob.glob('/proc/[0-9]*'):
        pid = int(p.split('/')[-1])
        try:
            with open(p + '/stat') as f:
                data = f.read()
            # comm puede tener espacios entre paréntesis
            rp = data.rfind(')')
            ppid = int(data[rp+2:].split()[1])
            with open(p + '/cmdline', 'rb') as f:
                cmd = f.read().replace(b'\x00', b' ').decode('utf-8', 'replace')
            out[pid] = {'ppid': ppid, 'cmd': cmd}
        except Exception:
            continue
    return out

def pss_rss_kb(pid):
    pss = rss = 0
    try:
        with open(f'/proc/{pid}/smaps_rollup') as f:
            for ln in f:
                if ln.startswith('Pss:'): pss = int(ln.split()[1])
                elif ln.startswith('Rss:'): rss = int(ln.split()[1])
    except Exception:
        pass
    return pss, rss

def main():
    P = procs()
    ch = {}
    for pid, v in P.items():
        ch.setdefault(v['ppid'], []).append(pid)
    # raíz: el start_driver.py del LIVE
    live_root = None
    for pid, v in P.items():
        if 'start_driver.py' in v['cmd'] and ('--label live' in v['cmd'] or 'live_driver.json' in v['cmd']):
            live_root = pid; break
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    if not live_root:
        line = f'{ts},NA,NA,0,driver_live_CAIDO'
        print(line)
        with open(CSV, 'a') as f: f.write(line + '\n')
        return
    # árbol
    tree = [live_root]; st = [live_root]
    while st:
        n = st.pop()
        for c in ch.get(n, []):
            tree.append(c); st.append(c)
    pss = rss = 0; n = 0
    for pid in tree:
        a, b = pss_rss_kb(pid)
        if a or b: n += 1
        pss += a; rss += b
    line = f'{ts},{pss/1024:.0f},{rss/1024:.0f},{n},ok'
    print(line)
    # encabezado si el archivo es nuevo
    new = not os.path.exists(CSV) or os.path.getsize(CSV) == 0
    with open(CSV, 'a') as f:
        if new: f.write('ts,pss_mb,rss_mb,nprocs,estado\n')
        f.write(line + '\n')

if __name__ == '__main__':
    main()
