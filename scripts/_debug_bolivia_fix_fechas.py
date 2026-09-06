#!/usr/bin/env python3
"""Corrige la FECHA (match_date) de los partidos PASADOS de Bolivia/Division
Profesional con score=-1 que en realidad fueron POSPUESTOS (aparecen en FIXTURES
de FlashScore con fecha futura). SOLO UPDATE de match.match_date. No toca score,
status, ni el driver (get_driver, nunca quit).

Flujo: (1) lee de BD los partidos flagged; (2) scrapea FIXTURES; (3) pareo estricto
por equipos -> nueva fecha; (4) imprime PLAN; (5) si APPLY=1, aplica UPDATE y verifica.
"""
import sys, os, time, unicodedata
sys.path.insert(0, '.'); sys.path.insert(0, 'src')
import config, psycopg2
from scripts.driver_session import get_driver
from selenium.webdriver.common.by import By

FIXTURES = "https://www.flashscore.com/football/bolivia/division-profesional/fixtures/"
APPLY = os.environ.get("APPLY") == "1"
YEAR = 2026  # fixtures vigentes son 2026

def norm(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii','ignore').decode().lower()
    return ' '.join(s.split())

def db():
    return psycopg2.connect(host=config.DB_HOST, dbname=config.DB_NAME,
                            user=config.DB_USER, password=config.DB_PASS, connect_timeout=20)

def read_flagged():
    c = db(); c.set_session(readonly=True, autocommit=True); cur = c.cursor()
    cur.execute("SET client_min_messages TO ERROR")
    cur.execute("""
      SELECT m.match_id, m.match_date, md_home.home_name, md_away.away_name, m.name
      FROM match m
      JOIN league l ON l.league_id=m.league_id
      LEFT JOIN country co ON co.country_id=m.country_id
      JOIN LATERAL (SELECT string_agg(t.team_name,'') home_name FROM match_detail md
                    JOIN team t ON t.team_id=md.team_id WHERE md.match_id=m.match_id AND md.home='true') md_home ON true
      JOIN LATERAL (SELECT string_agg(t.team_name,'') away_name FROM match_detail md
                    JOIN team t ON t.team_id=md.team_id WHERE md.match_id=m.match_id AND md.visitor='true') md_away ON true
      WHERE l.league_name ILIKE '%Division Profesional%' AND co.country_name='BOLIVIA'
        AND m.match_date < CURRENT_DATE
        AND EXISTS (SELECT 1 FROM match_detail md2 JOIN score_entity se2 ON se2.match_detail_id=md2.match_detail_id
                    WHERE md2.match_id=m.match_id AND se2.points=-1)
      GROUP BY m.match_id, m.match_date, md_home.home_name, md_away.away_name, m.name
      ORDER BY m.match_date;
    """)
    rows = cur.fetchall(); c.close()
    # fallback: usar m.name (home~visitor) si los nombres via team salen vacios
    out = []
    for mid, mdate, hn, an, name in rows:
        if not hn or not an:
            parts = (name or '').split('~')
            hn = hn or (parts[0] if parts else '')
            an = an or (parts[1] if len(parts) > 1 else '')
        out.append({"id": mid, "old": mdate, "home": hn, "away": an, "name": name})
    return out

def scrape_fixtures(driver):
    rows = []
    for attempt in range(1, 4):
        driver.get(FIXTURES); time.sleep(2)
        for txt in ("I Accept","Acepto","Consent"):
            try:
                driver.find_element(By.XPATH, f"//button[contains(.,'{txt}')]").click(); time.sleep(1)
            except Exception: pass
        # esperar a que aparezcan filas (hasta ~15s)
        found = 0
        for _ in range(15):
            found = len(driver.find_elements(By.CLASS_NAME, "event__match"))
            if found > 0: break
            time.sleep(1)
        print(f"  [scrape intento {attempt}] url={driver.current_url}  event__match={found}")
        if found > 0:
            # forzar render perezoso del tiempo: scroll incremental hasta el fondo y volver
            h = driver.execute_script("return document.body.scrollHeight")
            for y in range(0, h, 600):
                driver.execute_script(f"window.scrollTo(0,{y});"); time.sleep(0.15)
            driver.execute_script("window.scrollTo(0,0);"); time.sleep(1)
            sample = [e.text.strip() for e in driver.find_elements(By.XPATH, '//*[contains(@class,"event__stageTime")]')[:5]]
            print(f"    muestra event__time: {sample}")
            break
    for r in driver.find_elements(By.CLASS_NAME, "event__match"):
        try:
            h = r.find_element(By.XPATH, './/*[contains(@class,"event__homeParticipant")]').text.strip()
            a = r.find_element(By.XPATH, './/*[contains(@class,"event__awayParticipant")]').text.strip()
        except Exception:
            try:
                h = r.find_element(By.XPATH, './/*[contains(@class,"event__participant--home")]').text.strip()
                a = r.find_element(By.XPATH, './/*[contains(@class,"event__participant--away")]').text.strip()
            except Exception:
                continue
        t = ""
        for cls in ("event__stageTime", "event__time", "wcl-stageTime"):
            try:
                t = r.find_element(By.XPATH, f'.//*[contains(@class,"{cls}")]').text.strip()
                if t:
                    break
            except Exception:
                pass
        if h and a:
            rows.append({"home": h, "away": a, "time": t})
    return rows

def parse_date(t):
    # "02.08. 21:00" -> (2026-08-02, '21:00')
    try:
        dm = t.split()[0].strip(".")        # "02.08"
        dd, mm = dm.split(".")[:2]
        return f"{YEAR}-{int(mm):02d}-{int(dd):02d}", (t.split()[1] if len(t.split())>1 else "")
    except Exception:
        return None, None

def match_fix(fixtures, home, away):
    nh, na = norm(home), norm(away)
    for f in fixtures:
        fh, fa = norm(f["home"]), norm(f["away"])
        if nh==fh and na==fa: return f, "directo"
    for f in fixtures:
        fh, fa = norm(f["home"]), norm(f["away"])
        if nh==fa and na==fh: return f, "invertido"
    return None, None

def main():
    flagged = read_flagged()
    print(f"Partidos flagged (pasados, score=-1): {len(flagged)}")
    driver = get_driver()
    fixtures = scrape_fixtures(driver)
    print(f"Fixtures FlashScore leidos: {len(fixtures)}\n")

    plan = []
    print("="*90); print("  PLAN (old -> new)"); print("="*90)
    for m in flagged:
        f, kind = match_fix(fixtures, m["home"], m["away"])
        if not f:
            print(f"  [SKIP] {m['old']} {m['name']} -> sin pareo en fixtures")
            continue
        newd, newt = parse_date(f["time"])
        if not newd:
            print(f"  [SKIP] {m['old']} {m['name']} -> no pude parsear fecha '{f['time']}'")
            continue
        plan.append((m["id"], m["old"], newd))
        print(f"  {m['name']:<38} {m['old']}  ->  {newd}  ({kind}, FS time='{f['time']}')")

    print(f"\nTotal a actualizar: {len(plan)} de {len(flagged)}")

    if not APPLY:
        print("\n(DRY-RUN — no se escribio nada. Exporta APPLY=1 para aplicar.)")
        return

    print("\n--- APLICANDO UPDATE match.match_date ---")
    c = db(); c.autocommit = False; cur = c.cursor()
    cur.execute("SET client_min_messages TO ERROR")
    for mid, old, newd in plan:
        cur.execute("UPDATE match SET match_date=%s WHERE match_id=%s", (newd, mid))
        print(f"  UPDATE {mid}  {old} -> {newd}  (rows={cur.rowcount})")
    c.commit()
    print(f"COMMIT ok ({len(plan)} filas).")

    # verificacion
    cur2 = c.cursor(); cur2.execute("SET client_min_messages TO ERROR")
    cur2.execute("""
      SELECT count(*) FROM match m JOIN league l ON l.league_id=m.league_id
      LEFT JOIN country co ON co.country_id=m.country_id
      JOIN match_detail md ON md.match_id=m.match_id JOIN score_entity se ON se.match_detail_id=md.match_detail_id
      WHERE l.league_name ILIKE '%Division Profesional%' AND co.country_name='BOLIVIA'
        AND se.points=-1 AND m.match_date < CURRENT_DATE
    """)
    print("VERIFICACION -> Bolivia score=-1 PASADOS restantes:", cur2.fetchone()[0])
    c.close()

if __name__ == "__main__":
    main()
