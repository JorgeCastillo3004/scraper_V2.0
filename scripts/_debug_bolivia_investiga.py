#!/usr/bin/env python3
"""READ-ONLY: investiga los 8 partidos pasados de Bolivia/Division Profesional
con score=-1. Navega FlashScore (results + fixtures + archive) reusando el driver
vivo (get_driver, NUNCA quit) y reporta si cada partido aparece y con qué score.

No escribe en BD ni toca el driver (no quit/pkill)."""
import sys, time, unicodedata
sys.path.insert(0, '.'); sys.path.insert(0, 'src')
from scripts.driver_session import get_driver
from selenium.webdriver.common.by import By

RESULTS  = "https://www.flashscore.com/football/bolivia/division-profesional/results/"
FIXTURES = "https://www.flashscore.com/football/bolivia/division-profesional/fixtures/"
ARCHIVE  = "https://www.flashscore.com/football/bolivia/division-profesional/archive/"

# Los 8 PASADOS con score=-1 (home, away)
TARGETS = [
    ("2026-06-19", "Real Potosi", "GV San Jose"),
    ("2026-06-20", "SA Bulo Bulo", "Blooming"),
    ("2026-06-20", "Universitario de Vinto", "Guabira"),
    ("2026-06-20", "Tomayapo", "Academia del Balompie"),
    ("2026-06-21", "The Strongest", "Aurora"),
    ("2026-06-21", "Always Ready", "Bolivar"),
    ("2026-06-21", "Real Oruro", "Independiente"),
    ("2026-06-22", "Oriente Petrolero", "Nacional Potosi"),
]

def norm(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii','ignore').decode().lower()
    return ' '.join(s.split())

def load_all(driver, url, max_more=40):
    driver.get(url)
    time.sleep(3)
    # cerrar consentimiento de cookies si aparece
    for txt in ("I Accept", "Acepto", "Consent"):
        try:
            b = driver.find_element(By.XPATH, f"//button[contains(.,'{txt}')]")
            b.click(); time.sleep(1)
        except Exception:
            pass
    # click "show more" hasta agotar
    clicks = 0
    while clicks < max_more:
        try:
            more = driver.find_element(By.CLASS_NAME, "event__more")
            driver.execute_script("arguments[0].scrollIntoView(true);", more)
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", more)
            clicks += 1; time.sleep(1.5)
        except Exception:
            break
    return clicks

def scrape_rows(driver):
    out = []
    rows = driver.find_elements(By.CLASS_NAME, "event__match")
    for r in rows:
        try:
            h = r.find_element(By.XPATH, './/*[contains(@class,"event__homeParticipant")]').text.strip()
            a = r.find_element(By.XPATH, './/*[contains(@class,"event__awayParticipant")]').text.strip()
        except Exception:
            try:
                h = r.find_element(By.XPATH, './/*[contains(@class,"event__participant--home")]').text.strip()
                a = r.find_element(By.XPATH, './/*[contains(@class,"event__participant--away")]').text.strip()
            except Exception:
                continue
        def safe(xp):
            try: return r.find_element(By.XPATH, xp).text.strip()
            except Exception: return ""
        hs = safe('.//*[contains(@class,"event__score--home")]')
        as_ = safe('.//*[contains(@class,"event__score--away")]')
        tm = safe('.//*[contains(@class,"event__time")]')
        st = safe('.//*[contains(@class,"event__stage")]')
        out.append({"home":h,"away":a,"hs":hs,"as":as_,"time":tm,"stage":st})
    return out

def find_target(rows, home, away):
    nh, na = norm(home), norm(away)
    for row in rows:
        rh, ra = norm(row["home"]), norm(row["away"])
        # coincidencia flexible: contiene en cualquier sentido
        if (nh in rh or rh in nh or any(w in rh for w in nh.split() if len(w)>3)) and \
           (na in ra or ra in na or any(w in ra for w in na.split() if len(w)>3)):
            return row
    return None

def strict_find(rows, home, away):
    """Pareo ESTRICTO: ambos equipos iguales (normalizados), en orden o invertido."""
    nh, na = norm(home), norm(away)
    for row in rows:
        rh, ra = norm(row["home"]), norm(row["away"])
        if nh == rh and na == ra:
            return row, "directo"
        if nh == ra and na == rh:
            return row, "invertido"
    return None, None

def main():
    driver = get_driver()
    print("driver OK, url actual:", driver.current_url)

    store = {}
    for label, url in (("RESULTS", RESULTS), ("FIXTURES", FIXTURES)):
        print("\n" + "="*78)
        print(f"  {label}: {url}")
        print("="*78)
        clicks = load_all(driver, url)
        rows = scrape_rows(driver)
        store[label] = rows
        print(f"  show-more clicks={clicks} | filas encontradas={len(rows)}")
        print(f"  VOLCADO COMPLETO {label}:")
        for r in rows:
            print(f"     {r['time']:>12}  {r['home']:<26} {r['hs']:>2}-{r['as']:<2} {r['away']}")

    print("\n" + "#"*78)
    print("  PAREO ESTRICTO de los 8 objetivo (RESULTS y FIXTURES)")
    print("#"*78)
    for d, h, a in TARGETS:
        rrow, rkind = strict_find(store["RESULTS"], h, a)
        frow, fkind = strict_find(store["FIXTURES"], h, a)
        print(f"\n  [{d}] {h} ~ {a}")
        if rrow:
            print(f"     RESULTS : {rkind}  '{rrow['home']}' {rrow['hs']}-{rrow['as']} '{rrow['away']}' time={rrow['time']}")
        else:
            print(f"     RESULTS : NO esta")
        if frow:
            print(f"     FIXTURES: {fkind}  '{frow['home']}' --- '{frow['away']}' nueva_fecha={frow['time']}")
        else:
            print(f"     FIXTURES: NO esta")

    # ARCHIVE: ver temporadas (¿Apertura/Clausura?)
    print("\n" + "="*78); print(f"  ARCHIVE: {ARCHIVE}"); print("="*78)
    driver.get(ARCHIVE); time.sleep(3)
    try:
        arows = driver.find_elements(By.XPATH, "//*[contains(@class,'archive__row')]")
        for ar in arows[:15]:
            print("   ", " | ".join(ar.text.split("\n")))
    except Exception as e:
        print("   (no se pudo leer archive:", e, ")")

    print("\n[done] driver intacto (sin quit).")

if __name__ == "__main__":
    main()
