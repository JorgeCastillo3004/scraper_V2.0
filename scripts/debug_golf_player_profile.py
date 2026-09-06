"""
scripts/debug_golf_player_profile.py
─────────────────────────────────────
Navega a un torneo Golf en FlashScore, extrae el primer player_url
y vuelca el HTML relevante del perfil para identificar los nuevos
selectores wcl-* que reemplazan a tournamentHeader__*.

Uso:
    python scripts/debug_golf_player_profile.py
"""
import sys, os, re, time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'src'))

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from common_functions import launch_navigator, dismiss_cookies

RESULTS_URL = "https://www.flashscore.com/golf/pga-tour/the-players-championship/results/"

def get_player_url_from_block(player_block):
    html_block = player_block.get_attribute('outerHTML')
    match = re.findall(r'id="[a-z]\_\d+\_(.+?)"', html_block)
    if not match:
        return None
    return "https://www.flashscore.com/match/{}/p/#/match-summary".format(match[0])

def main():
    driver = launch_navigator('https://www.flashscore.com', headless=False)
    try:
        print(f"[1] Navegando a resultados: {RESULTS_URL}")
        driver.get(RESULTS_URL)
        time.sleep(4)
        dismiss_cookies(driver)
        time.sleep(2)

        # Buscar bloques de torneo
        event_blocks = driver.find_elements(By.CLASS_NAME, 'sportName--noDuel')
        print(f"[2] Torneos encontrados: {len(event_blocks)}")
        if not event_blocks:
            print("[ERROR] No se encontraron torneos. Verificar URL o selectores.")
            return

        # Primer torneo, primer jugador
        event_block = event_blocks[0]
        players = event_block.find_elements(By.XPATH, './/div[@data-event-row="true"]')
        print(f"[3] Jugadores en primer torneo: {len(players)}")
        if not players:
            print("[ERROR] No se encontraron jugadores.")
            return

        player_url = get_player_url_from_block(players[0])
        print(f"[4] Player URL: {player_url}")
        if not player_url:
            print("[ERROR] No se pudo extraer la URL del jugador.")
            return

        # Navegar al perfil del jugador
        print(f"[5] Navegando al perfil del jugador...")
        driver.get(player_url)
        time.sleep(5)

        # Volcar HTML del body completo
        body_html = driver.find_element(By.TAG_NAME, 'body').get_attribute('innerHTML')

        # Buscar bloques con clases que contengan palabras clave
        keywords = ['participant', 'header', 'wcl-', 'playerProfile', 'golfer', 'athlete', 'profile']
        print("\n" + "="*60)
        print("CLASES CSS RELEVANTES EN LA PÁGINA:")
        print("="*60)
        all_classes = re.findall(r'class="([^"]+)"', body_html)
        seen = set()
        for cls_group in all_classes:
            for cls in cls_group.split():
                if any(kw in cls.lower() for kw in keywords) and cls not in seen:
                    seen.add(cls)
                    print(f"  {cls}")

        print("\n" + "="*60)
        print("TÍTULO DEL JUGADOR (texto del h1/h2/heading):")
        print("="*60)
        for tag in ['h1', 'h2', 'h3']:
            els = driver.find_elements(By.TAG_NAME, tag)
            for el in els:
                txt = el.text.strip()
                if txt:
                    print(f"  <{tag}> class='{el.get_attribute('class')}' text='{txt[:80]}'")

        # Intentar encontrar el nombre del jugador por texto prominente
        print("\n" + "="*60)
        print("ELEMENTOS CON CLASE wcl-* O tournamentHeader*):")
        print("="*60)
        wcl_els = driver.find_elements(By.XPATH, '//*[contains(@class,"wcl-") or contains(@class,"tournamentHeader") or contains(@class,"participant")]')
        for el in wcl_els[:40]:
            cls = el.get_attribute('class')
            txt = el.text.strip()[:60]
            tag = el.tag_name
            print(f"  <{tag}> class='{cls}' text='{txt}'")

        # Guardar HTML completo para inspección
        out_path = os.path.join(_ROOT, 'scripts', 'debug_golf_player.html')
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
        print(f"\n[6] HTML completo guardado en: {out_path}")

    finally:
        driver.quit()

if __name__ == '__main__':
    main()
