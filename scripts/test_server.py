"""
test_server.py — Servidor FastAPI para pruebas de milestone6

Funcionamiento:
  1. FastAPI mantiene el driver Selenium vivo en memoria como variable global.
  2. Cada endpoint ejecuta una función del scraper usando ese driver compartido.
  3. Claude (o cualquier cliente) hace requests HTTP para disparar pruebas
     sin necesidad de relanzar el browser en cada prueba.

Uso:
  # Arrancar el servidor (desde raíz del proyecto):
  source /home/you/env/sports_env/bin/activate
  python scripts/test_server.py

  # Endpoints disponibles (ver abajo):
  curl -s http://localhost:8765/status
  curl -s -X POST http://localhost:8765/start
  curl -s -X POST http://localhost:8765/squad   -H "Content-Type: application/json" -d '{"url":"https://..."}'
  curl -s -X POST http://localhost:8765/player  -H "Content-Type: application/json" -d '{"url":"https://..."}'
  curl -s -X POST http://localhost:8765/players_league -H "Content-Type: application/json" -d '{"sport":"FOOTBALL","league":"ARGENTINA_Liga Profesional"}'
  curl -s -X POST http://localhost:8765/stop
"""

import sys
import os
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from pydantic import BaseModel
from selenium.webdriver.common.by import By
import uvicorn

from common_functions import *
from data_base import *
from milestone3 import *
from milestone6 import *
from config import FS_EMAIL, FS_PASSWORD

# ── Conexión DB — siempre activa (necesaria para check_player_duplicates) ──────
try:
    con = getdb()
    print("[DB] Conexión establecida")
except Exception as _db_err:
    print(f"[DB] Advertencia: no se pudo conectar — {_db_err}")
    con = None

# ── Estado global ──────────────────────────────────────────────────────────────
app = FastAPI(title="Scraper Test Server")
driver = None          # Selenium WebDriver — vive durante toda la sesión del servidor
driver_ready = False   # True después de /start exitoso

# ── Modelos de request ─────────────────────────────────────────────────────────
class UrlRequest(BaseModel):
    url: str

class LeagueRequest(BaseModel):
    sport: str
    league: str = ""       # vacío = procesa todas las ligas del sport

# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/status")
def status():
    """Devuelve si el driver está activo y en qué URL está."""
    if not driver_ready or driver is None:
        return {"driver": "stopped", "url": None}
    try:
        current_url = driver.current_url
        return {"driver": "running", "url": current_url}
    except Exception as e:
        return {"driver": "error", "error": str(e)}


@app.post("/start")
def start(headless: bool = False):
    """
    Lanza el browser Firefox y hace login en FlashScore.
    headless=False → browser visible (default para pruebas).
    headless=True  → sin ventana (para ejecución en servidor).
    """
    global driver, driver_ready
    try:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
        driver = launch_navigator('https://www.flashscore.com', headless=headless)
        login(driver, email_=FS_EMAIL, password_=FS_PASSWORD)
        driver_ready = True
        return {"status": "ok", "message": "Driver iniciado y login exitoso"}
    except Exception as e:
        driver_ready = False
        return {"status": "error", "error": str(e)}


@app.post("/squad")
def squad(req: UrlRequest):
    """
    Navega a la URL de squad de un equipo y devuelve la lista de links de jugadores.
    Ejemplo: {"url": "https://www.flashscore.com/team/velez-sarsfield/UsCR8gFd/squad/"}
    """
    if not driver_ready:
        return {"status": "error", "error": "Driver no iniciado. Llama /start primero."}
    try:
        wait_update_page(driver, req.url, 'heading')
        links = get_squad_list(driver, sport_id='FOOTBALL')
        return {"status": "ok", "count": len(links), "players": links}
    except Exception as e:
        return {"status": "error", "error": str(e), "trace": traceback.format_exc()}


@app.post("/player")
def player(req: UrlRequest):
    """
    Navega al perfil de un jugador y extrae sus datos.
    Ejemplo: {"url": "https://www.flashscore.com/player/montero-alvaro/Kv30f5AC/"}
    """
    if not driver_ready:
        return {"status": "error", "error": "Driver no iniciado. Llama /start primero."}
    try:
        wait_update_page(driver, req.url, 'container__heading')
        player_dict = get_player_data(driver)
        # datetime no es serializable — convertir a string
        player_dict['player_dob'] = str(player_dict['player_dob'])
        return {"status": "ok", "player": player_dict}
    except Exception as e:
        return {"status": "error", "error": str(e), "trace": traceback.format_exc()}


@app.post("/players_league")
def players_league(req: LeagueRequest):
    """
    Ejecuta players() para un sport completo o una liga específica.
    Si 'league' está vacío procesa todas las ligas del sport.
    Ejemplo: {"sport": "FOOTBALL", "league": "ARGENTINA_Liga Profesional"}
    """
    if not driver_ready:
        return {"status": "error", "error": "Driver no iniciado. Llama /start primero."}
    try:
        if req.league:
            # Ejecutar players() solo para esta liga
            leagues_info = load_check_point('check_points/leagues_info.json')
            if req.sport not in leagues_info:
                return {"status": "error", "error": f"Sport '{req.sport}' no encontrado"}
            if req.league not in leagues_info[req.sport]:
                return {"status": "error", "error": f"Liga '{req.league}' no encontrada en {req.sport}"}

            path = f'check_points/leagues_season/{req.sport}/{req.league}.json'
            if not os.path.isfile(path):
                return {"status": "error", "error": f"Archivo no existe: {path}"}

            league_info = leagues_info[req.sport][req.league]
            dict_league_season = load_check_point(path)

            for team_name, team_info in dict_league_season.items():
                print_section(team_name, space_=20)

                if team_info.get('last_processed') == 'completed':
                    print(f"  [SKIP] Equipo ya completado: {team_name}")
                    continue

                if team_info.get('url_players'):
                    print(f"  [RESUME] url_players ya guardado ({len(team_info['url_players'])} jugadores)")
                else:
                    if not team_info.get('team_url'):
                        print(f"  [WARN] team_url vacío para {team_name} — saltando equipo")
                        continue
                    wait_update_page(driver, team_info['team_url'], 'container__heading')
                    squad_url = None
                    try:
                        squad_button = driver.find_element(By.CLASS_NAME, 'tabs__tab.squad')
                        squad_url = squad_button.get_attribute('href')
                    except Exception:
                        try:
                            squad_button = driver.find_element(By.XPATH, '//a[@title="Squad"]')
                            squad_url = squad_button.get_attribute('href')
                        except Exception:
                            print(f"  [WARN] Squad button no encontrado: {team_name} — saltando")
                            continue
                    wait_update_page(driver, squad_url, 'heading')
                    list_squad = get_squad_list(driver, sport_id=req.sport)
                    print(f"  [INFO] {len(list_squad)} jugadores obtenidos para {team_name}")
                    dict_league_season[team_name]['url_players'] = list_squad
                    dict_league_season[team_name]['last_processed'] = -1
                    save_check_point(path, dict_league_season)

                navigate_through_players(
                    driver, req.league, team_name,
                    league_info['season_id'], team_info['team_id'],
                    dict_league_season[team_name], path,
                    dict_league_season, req.sport
                )

            return {"status": "ok", "message": f"players() completado para {req.sport}/{req.league}"}
        else:
            players(driver, [req.sport])
            return {"status": "ok", "message": f"players() completado para {req.sport}"}
    except Exception as e:
        return {"status": "error", "error": str(e), "trace": traceback.format_exc()}


@app.post("/debug_tabs")
def debug_tabs(req: UrlRequest):
    """
    Debug: navega a la URL y retorna TODOS los wcl-tabs encontrados,
    mostrando data-type para identificar si son primary o secondary.
    """
    if not driver_ready:
        return {"status": "error", "error": "Driver no iniciado."}
    try:
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        wait_update_page(driver, req.url, 'container__heading')
        import time; time.sleep(2)
        result = {}
        result['current_url'] = driver.current_url
        for dtype in ['primary', 'secondary', 'any']:
            if dtype == 'any':
                xpath = '//div[@data-testid="wcl-tabs"]/a'
            else:
                xpath = f'//div[@data-testid="wcl-tabs" and @data-type="{dtype}"]/a'
            tabs = driver.find_elements(By.XPATH, xpath)
            result[dtype] = [
                {"label": t.find_elements(By.XPATH, './/button')[0].text if t.find_elements(By.XPATH, './/button') else '',
                 "href": t.get_attribute('href')}
                for t in tabs if t.get_attribute('href')
            ]
        return {"status": "ok", "tabs": result}
    except Exception as e:
        return {"status": "error", "error": str(e), "trace": traceback.format_exc()}


@app.post("/teams_part1")
def teams_part1(req: UrlRequest):
    """Debug: navega a URL y ejecuta get_teams_info_part1 directamente."""
    if not driver_ready:
        return {"status": "error", "error": "Driver no iniciado."}
    try:
        wait_update_page(driver, req.url, 'container__heading')
        teams = get_teams_info_part1(driver)
        return {"status": "ok", "count": len(teams), "teams": list(teams.keys())}
    except Exception as e:
        return {"status": "error", "error": str(e), "trace": traceback.format_exc()}


@app.post("/teams_standings")
def teams_standings(req: UrlRequest):
    """
    Prueba get_all_teams_from_standings(driver, url).
    Retorna los equipos encontrados (nombre + team_url), incluyendo divisiones si las hay.
    Ejemplo: {"url": "https://www.flashscore.com/football/belgium/jupiler-pro-league/standings/"}
    """
    if not driver_ready:
        return {"status": "error", "error": "Driver no iniciado. Llama /start primero."}
    try:
        teams = get_all_teams_from_standings(driver, req.url)
        result = {name: info.get('team_url', '') for name, info in teams.items()}
        return {"status": "ok", "count": len(result), "teams": result}
    except Exception as e:
        return {"status": "error", "error": str(e), "trace": traceback.format_exc()}


@app.post("/navigate")
def navigate(req: UrlRequest):
    """Navega a cualquier URL con el driver. Útil para inspección manual."""
    if not driver_ready:
        return {"status": "error", "error": "Driver no iniciado."}
    try:
        driver.get(req.url)
        return {"status": "ok", "url": driver.current_url, "title": driver.title}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/stop")
def stop():
    """Cierra el browser y libera recursos."""
    global driver, driver_ready
    try:
        if driver:
            driver.quit()
        driver = None
        driver_ready = False
        return {"status": "ok", "message": "Driver cerrado"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Arranque ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Iniciando test_server en http://localhost:8765")
    print("Endpoints: /status /start /squad /player /players_league /navigate /stop")
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="info")
