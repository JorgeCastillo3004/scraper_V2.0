import psycopg2
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from config import DB_HOST, DB_NAME, DB_USER, DB_PASS
from common_functions import load_json, red_box_warning
from unidecode import unidecode
import re
import hashlib
import pycountry

def getdb():
    return psycopg2.connect(
        host=DB_HOST, dbname=DB_NAME, user=DB_USER, password=DB_PASS,
        connect_timeout=10,          # falla rápido si el servidor no responde al conectar
        keepalives=1,                # activa TCP keepalive a nivel de socket
        keepalives_idle=30,          # envía keepalive tras 30 s sin actividad
        keepalives_interval=5,       # reenvía cada 5 s si no hay respuesta
        keepalives_count=3,          # 3 fallos consecutivos → conexión muerta
        options="-c statement_timeout=30000"  # cualquier query >30 s lanza error
    )

def ensure_connection():
    """
    Verifica que la conexión global esté activa y la regenera si falló.
    Con statement_timeout=30s y keepalives cortos, el SELECT 1 ya no cuelga:
    detecta conexiones half-open en ~45 s (30 idle + 3×5 s keepalive).
    """
    global con
    try:
        con.cursor().execute("SELECT 1")
    except Exception:
        try:
            con.close()
        except Exception:
            pass
        con = getdb()
        print("DB reconnected")

def save_news_database(dict_news):
    ensure_connection()
    try:
        cur = con.cursor()
        # Anti-duplicado: la tabla `news` no tiene constraint único, así que
        # verificamos existencia ANTES de insertar. La clave es (title,
        # news_content): la MISMA noticia es mismo título + mismo cuerpo,
        # independiente de `published` (las noticias recientes traen fecha
        # RELATIVA "X min ago" y `process_date` la calcula contra el "ahora" de
        # cada corrida → `published` varía y un dedup por fecha dejaba pasar
        # near-duplicados). Con (title, news_content) se preservan los títulos
        # repetidos que son noticias DISTINTAS (contenido distinto). Idempotente.
        cur.execute(
            "SELECT 1 FROM news WHERE title = %(title)s AND news_content = %(news_content)s LIMIT 1",
            dict_news,
        )
        if cur.fetchone():
            con.commit()
            return False  # ya existe → no reinsertar
        query = "INSERT INTO news VALUES(%(news_id)s, %(news_content)s, %(image)s,\
                %(published)s, %(news_summary)s, %(news_tags)s, %(title)s)"
        cur.execute(query, dict_news)
        con.commit()
        return True
    except:
        print("###### ERROR SAVING NEWS ######")
        con.rollback()
        return False


def news_exists(title, published):
    """True si ya existe una noticia con ese (title, published) en DB.
    Se usa como early-skip ANTES de navegar a la página de la noticia, para
    que las reanudaciones de FASE 2 no re-naveguen miles de noticias ya
    guardadas (la FASE-1 ya trae title+published en el JSON)."""
    ensure_connection()
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT 1 FROM news WHERE title = %s AND published = %s LIMIT 1",
            (title, published),
        )
        found = cur.fetchone() is not None
        con.commit()
        return found
    except:
        con.rollback()
        return False

def save_sport_database(sport_dict):
    ensure_connection()
    try:
        query = "INSERT INTO sport VALUES(%(sport_id)s, %(is_active)s, %(desc_i18n)s,\
                                         %(logo)s, %(sport_mode)s, %(name_i18n)s, %(point_name)s, %(name)s)"
        cur = con.cursor()
        cur.execute(query, sport_dict)
        con.commit()
    except:
        con.rollback()

def get_country_list():
    """
    Returns a list of country names in English using pycountry.
    """
    return [country.name for country in pycountry.countries]

def generate_unique_id(input_string):
    """
    Generates a unique 17-character ID from a given string.
    The same input will always generate the same output.
    
    :param input_string: The input string (e.g., a country name).
    :return: A unique 17-character string ID.
    """
    # Step 1: Normalize the input string (strip spaces, convert to lowercase)
    normalized_string = input_string.strip().lower()
    
    # Step 2: Create a SHA-256 hash of the normalized string
    hash_object = hashlib.sha256(normalized_string.encode())  
    hex_hash = hash_object.hexdigest()  # Convert hash to hexadecimal string
    
    # Step 3: Convert the hexadecimal hash to base 36 (more compact and readable)
    base36_hash = int(hex_hash, 16)  # Convert hex to integer
    base36_string = base36_encode(base36_hash)  # Convert to base 36
    
    # Step 4: Return the first 17 characters to ensure a fixed-length ID
    return base36_string[:17]

def base36_encode(number):
    """Encodes an integer into a base-36 string."""
    alphabet = '0123456789abcdefghijklmnopqrstuvwxyz'
    base36 = ''
    
    while number:
        number, i = divmod(number, 36)
        base36 = alphabet[i] + base36
    
    return base36 or '0'

def insert_country(country_name):
    ensure_connection()
    cur = con.cursor()
    country_name = country_name.upper().split(',')[0]
    if ',' in country_name:
        country_name = country_name.split(',')[0]
    country_id = generate_unique_id(country_name)
    country_name_i18n = ''
    country_logo = ''
    dict_country = {'country_id': country_id, 'country_name': country_name,
                    'country_name_i18n': country_name_i18n, 'country_logo': country_logo}
    try:
        query = """INSERT INTO COUNTRY (country_id, country_name, country_name_i18n, country_logo) 
                    VALUES (%(country_id)s, %(country_name)s, %(country_name_i18n)s, %(country_logo)s)"""
        cur.execute(query, dict_country)
        con.commit()
        return country_id
    except:
        con.rollback()
        

def insert_countries_to_db(countries):
    ensure_connection()
    try:
        cur = con.cursor()  # Crear cursor fuera del bucle para eficiencia
        
        for country in countries:
            country = country.upper().split(',')[0]
            if ',' in country:
                country = country.split(',')[0]
            country_id = generate_unique_id(country)
            country_name_i18n = ''
            country_logo = ''
            dict_country = {'country_id': country_id, 'country_name': country,
                            'country_name_i18n': country_name_i18n, 'country_logo': country_logo}

            # Verificar si el país ya existe en la base de datos
            check_query = "SELECT 1 FROM COUNTRY WHERE country_id = %(country_id)s"
            cur.execute(check_query, {'country_id': country_id})
            exists = cur.fetchone()

            if exists:
                continue
                # print(f"⚠️ País '{country}' ya existe en la base de datos. Se omite la inserción.")
            else:
                query = """INSERT INTO COUNTRY (country_id, country_name, country_name_i18n, country_logo) 
                           VALUES (%(country_id)s, %(country_name)s, %(country_name_i18n)s, %(country_logo)s)"""
                cur.execute(query, dict_country)
                con.commit()
                print(f"✅ País '{country}' insertado correctamente.")

    except Exception as e:
        print(f"❌ Error: {e}")
        con.rollback()    

def create_country(country):
    ensure_connection()
    cur = con.cursor()  
    country_id = generate_unique_id(country)
    country_name_i18n = ''
    country_logo = ''
    dict_country = {'country_id': country_id, 'country_name': country,
                    'country_name_i18n': country_name_i18n, 'country_logo': country_logo}

    # Verificar si el país ya existe en la base de datos
    check_query = "SELECT 1 FROM COUNTRY WHERE country_id = %(country_id)s"
    cur.execute(check_query, {'country_id': country_id})
    exists = cur.fetchone()

    if exists:
        print(f"⚠️ País '{country}' ya existe en la base de datos. Se omite la inserción.")
    else:
        query = """INSERT INTO COUNTRY (country_id, country_name, country_name_i18n, country_logo) 
                    VALUES (%(country_id)s, %(country_name)s, %(country_name_i18n)s, %(country_logo)s)"""
        cur.execute(query, dict_country)
        con.commit()

def get_country_id(country_name):
    ensure_connection()
    """
    Retrieves the country_id from the database based on the given country_name.
    
    Parameters:
    - country_name (str): Name of the country to search for.
    - con (psycopg2.connection): Active database connection.

    Returns:
    - str: The country_id if found, otherwise None.
    """
    try:
        cur = con.cursor()
        
        # Query to search for the country in the database
        query = "SELECT country_id FROM COUNTRY WHERE UPPER(country_name) = UPPER(%s) LIMIT 1;"

        cur.execute(query, (country_name,))
        result = cur.fetchone()  # Fetch only one result
        
        cur.close()  # Close the cursor
        
        if result:
            return result[0]  # Return country_id
        else:
            print(f"⚠️ Country '{country_name}' not found in the database.")
            return None

    except Exception as e:
        print(f"❌ Error fetching country_id: {e}")
        return None

def get_dict_sport_id():
    ensure_connection()
    query = "SELECT sport.name, sport.sport_id FROM sport"
    # 
    # -- WHERE team.sport_id = '{}'
    cur = con.cursor()
    cur.execute(query)  
    dict_results = {row[0] : row[1] for row in cur.fetchall()}
    return dict_results

def save_league_info(dict_league_tornament):
    ensure_connection()
    query = "INSERT INTO league VALUES(%(league_id)s, %(country_id)s, %(league_logo)s, %(league_name)s, %(league_name_i18n)s, %(sport_id)s)"
    cur = con.cursor()                                                                           
    cur.execute(query, dict_league_tornament)                                                         
    con.commit()                                                                                     

def save_season_database(season_dict):
    ensure_connection()
    query = "INSERT INTO season VALUES(%(season_id)s, %(season_name)s, %(season_end)s,\
                                     %(season_start)s, %(league_id)s)"
    cur = con.cursor()
    cur.execute(query, season_dict)
    con.commit()

def save_tournament(dict_tournament):
    ensure_connection()
    query = "INSERT INTO tournament VALUES(%(tournament_id)s, %(team_country)s, %(desc_i18n)s,\
                                     %(end_date)s, %(logo)s, %(name_i18n)s, %(season)s, %(start_date)s, %(tournament_year)s)"
    cur = con.cursor()
    cur.execute(query, dict_tournament)
    con.commit()

def save_team_info(dict_team):
    ensure_connection()
    query = "INSERT INTO team VALUES(%(team_id)s, %(country_id)s, %(team_desc)s,\
     %(team_logo)s, %(team_name)s, %(sport_id)s)"
    cur = con.cursor()                                                                           
    cur.execute(query, dict_team)                                                        
    con.commit()

def get_season_id_by_league(league_id):
    ensure_connection()
    cur = con.cursor()
    cur.execute("SELECT season_id FROM season WHERE league_id = %s LIMIT 1", (league_id,))
    row = cur.fetchone()
    return row[0] if row else None

def save_league_team_entity(dict_team):
    ensure_connection()
    query = "INSERT INTO league_team VALUES(%(instance_id)s, %(team_meta)s, %(team_position)s, %(league_id)s, %(season_id)s, %(team_id)s)"  
    cur = con.cursor()
    cur.execute(query, dict_team)
    con.commit()

def save_player_info(dict_team):
    ensure_connection()
    query = "INSERT INTO player VALUES(%(player_id)s, %(country_id)s, %(player_dob)s,\
     %(player_name)s, %(player_photo)s, %(player_position)s)"
    cur = con.cursor()
    cur.execute(query, dict_team)
    con.commit()

def save_team_players_entity(player_dict):
    ensure_connection()
    query = "INSERT INTO team_players_entity VALUES(%(player_meta)s, %(season_id)s, %(team_id)s,\
     %(player_id)s)"
    cur = con.cursor()
    cur.execute(query, player_dict)
    con.commit()

def get_team_id(league_id, season_id, team_name):
    # NOTA (2026-06-13): esta función NO tiene llamadores en el proyecto — el flujo
    # de creación/lookup de equipos usa get_list_id_teams() + create_team_in_db().
    # Se deja neutralizada por las dudas: (1) parametrizada, para que un nombre con
    # apóstrofe (O'Higgins, M'Gladbach) NO rompa el SQL ni envenene la conexión si
    # algún flujo futuro la usa; (2) con guarda de None, porque el `results[0]`
    # crudo explotaba (TypeError) cuando el equipo no existía.
    ensure_connection()
    cur = con.cursor()
    cur.execute(
        """SELECT t2.team_id
           FROM league_team AS t1
           JOIN team AS t2 ON t1.team_id = t2.team_id
           WHERE t1.league_id = %s AND t1.season_id = %s AND t2.team_name = %s""",
        (league_id, season_id, team_name),
    )
    results = cur.fetchone()
    return results[0] if results else None

def get_seasons(league_id, season_name):
    ensure_connection()
    query = "SELECT season_name, season_id FROM season  WHERE league_id ='{}' and season_name = '{}';".format(league_id, season_name)
    cur = con.cursor()
    cur.execute(query)
    rows = cur.fetchall()
    results = [row[0] for row in rows]
    return results

def get_season_id_by_name(league_id, season_name):
    """Returns the season_id stored in DB for the given league+season_name, or None."""
    ensure_connection()
    cur = con.cursor()
    cur.execute(
        "SELECT season_id FROM season WHERE league_id = %s AND season_name = %s LIMIT 1",
        (league_id, season_name)
    )
    row = cur.fetchone()
    return row[0] if row else None

def get_list_id_teams(sport_id, country_id, team_name):
    ensure_connection()
    # parametrizado: team_name con apóstrofe (Xi'an, O'Higgins) rompía el .format
    cur = con.cursor()
    cur.execute("SELECT team_id FROM team WHERE sport_id = %s AND country_id = %s AND team_name = %s",
                (sport_id, country_id, team_name))
    results = [row[0] for row in cur.fetchall()]
    return results

def get_dict_results(table= 'league', columns = 'sport_id, league_country, league_name, league_id'):
    ensure_connection()
    query = f"SELECT {columns} FROM {table};"   
    cur = con.cursor()
    cur.execute(query)
    dict_results = {row[0] + '_'+ row[1] + '_' + row[2]: row[3] for row in cur.fetchall()}
    return dict_results

def get_dict_teams(sport_id = 'FOOTBALL'):
    ensure_connection()
    query = """
    SELECT league.league_country, team.team_name, team.team_id\
    FROM team \
    JOIN league_team ON team.team_id = league_team.team_id\
    JOIN league league_team.league_id = league.league_id    
    WHERE team.id_sport = '{}'""".format(sport_id)

    cur = con.cursor()
    cur.execute(query)

    dict_results = {unidecode('-'.join(row[0].replace('&', '').split() ) ).upper():\
                    {'team_name': unidecode('-'.join(row[1].split() ) ).upper(),\
                     'team_id': row[2]} for row in cur.fetchall()}
    return dict_results

def get_dict_league_ready(sport_id = 'TENNIS'):
    ensure_connection()
    query = """
        SELECT team.sport_id, team.country_id, league.country_id, team.team_name, team.team_id
        FROM team
        JOIN league_team ON team.team_id = league_team.team_id
        JOIN league ON league_team.league_id = league.league_id
        WHERE team.sport_id = '{}'""".format(sport_id)
    # 
    # -- WHERE team.sport_id = '{}'
    cur = con.cursor()
    cur.execute(query)
    results = cur.fetchall()
    dict_results = {}
    for row in results: 
        dict_results.setdefault(row[0], {}).setdefault(row[1], {}).setdefault(row[2], {})[row[3]] = {'team_id': row[4]} 

    return dict_results

######################################## FUNCTIONS RELATED TO MATCHS ########################################
def save_math_info(dict_match):
    ensure_connection()
    dict_match['rounds'] = ' '.join(dict_match['rounds'].split())    

    query = "INSERT INTO match VALUES(%(match_id)s, %(country_id)s, %(end_time)s,\
     %(match_date)s, %(name)s, %(place)s, %(start_time)s, %(league_id)s, \
     %(stadium_id)s, %(tournament_id)s,%(rounds)s, %(season_id)s, \
         %(statistic)s, %(status)s)"
    cur = con.cursor()
    cur.execute(query, dict_match)
    con.commit()

def save_details_math_info(dict_match):
    ensure_connection()
    query = "INSERT INTO match_detail VALUES(%(match_detail_id)s, %(home)s, %(visitor)s,\
     %(match_id)s, %(team_id)s)"
    cur = con.cursor()
    cur.execute(query, dict_match)
    con.commit()

def save_score_info(dict_match):
    ensure_connection()
    query = "INSERT INTO score_entity VALUES(%(score_id)s, %(points)s, %(match_detail_id)s)"
    cur = con.cursor()
    cur.execute(query, dict_match)
    con.commit()

def save_stadium_in_db(dict_match):
    ensure_connection()
    query = "INSERT INTO stadium VALUES(%(stadium_id)s, %(capacity)s,\
     %(desc_i18n)s, %(name)s, %(photo)s)"
    cur = con.cursor()
    cur.execute(query, dict_match)
    con.commit()
    # verificar que realmente se creó
    cur.execute("SELECT stadium_id FROM stadium WHERE stadium_id = %s", (dict_match['stadium_id'],))
    if cur.fetchone():
        print(f"[OK ] Stadium creado y verificado: {dict_match.get('name', dict_match['stadium_id'])}")
        return True
    print(f"[WARN] Stadium NO encontrado en DB tras INSERT: {dict_match.get('name', dict_match['stadium_id'])}")
    return False

def get_league_match_team_count(league_id):
    ensure_connection()
    cur = con.cursor()
    cur.execute(
        "SELECT COUNT(DISTINCT m.match_id), COUNT(DISTINCT md.team_id) "
        "FROM match m LEFT JOIN match_detail md ON md.match_id=m.match_id "
        "WHERE m.league_id = %s",
        (league_id,)
    )
    row = cur.fetchone()
    return (row[0] or 0, row[1] or 0)  # (match_count, team_count)

def get_teams_by_league_id(league_id, sport_id):
    """
    Retorna lista de (team_id, team_name) registrados en una liga específica
    vía league_team, filtrando también por sport_id para evitar colisiones
    entre ligas con el mismo nombre en distintos deportes.
    """
    ensure_connection()
    cur = con.cursor()
    cur.execute(
        "SELECT t.team_id, t.team_name FROM team t "
        "JOIN league_team lt ON t.team_id = lt.team_id "
        "WHERE lt.league_id = %s AND t.sport_id = %s",
        (league_id, sport_id)
    )
    return cur.fetchall()  # [(team_id, team_name), ...]

def get_rounds_ready(league_id, season_id):
    ensure_connection()
    """Check rounds ready saved in DB"""
    query = "SELECT DISTINCT rounds FROM match WHERE league_id = '{}' AND season_id = '{}';".format(league_id, season_id)       
    cur = con.cursor()
    cur.execute(query)  
    results = [row[0] for row in cur.fetchall()]
    return results

def check_league_duplicate(league_id):
    ensure_connection()
    query = "SELECT league_id FROM league WHERE league_id ='{}';".format(league_id) 
    cur = con.cursor()
    cur.execute(query)  
    results = [row[0] for row in cur.fetchall()]
    return results

def check_season_duplicate(season_id):
    ensure_connection()
    query = "SELECT season_id FROM season WHERE season_id ='{}';".format(season_id) 
    cur = con.cursor()
    cur.execute(query)  
    results = [row[0] for row in cur.fetchall()]
    return results

def check_player_duplicates(country_id, player_name, player_dob):
    ensure_connection()
    # parametrizado: player_name con apóstrofe (O'Brien, N'Golo) rompía el .format
    cur = con.cursor()
    cur.execute(
        "SELECT player_id FROM player WHERE country_id = %s AND player_name = %s AND player_dob = %s",
        (country_id, player_name, player_dob),
    )
    results = [row[0] for row in cur.fetchall()]
    return results

def check_player_duplicates_id(player_id):
    ensure_connection()
    query = "SELECT player_id FROM player WHERE player_id ='{}';".format(player_id) 
    cur = con.cursor()
    cur.execute(query)  
    results = [row[0] for row in cur.fetchall()]
    return results

def check_team_duplicates(team_name, sport_id):
    ensure_connection()
    cur = con.cursor()
    cur.execute("SELECT team_id FROM team WHERE team_name = %s AND sport_id = %s",
                (team_name, sport_id))
    results = [row[0] for row in cur.fetchall()]
    return results

def check_team_duplicates_id(team_id):
    ensure_connection()
    query = "SELECT team_id FROM team WHERE team_id ='{}';".format(team_id)
    print("check team duplicates")
    print(query)
    cur = con.cursor()
    cur.execute(query)  
    results = [row[0] for row in cur.fetchall()]
    return results

def get_team_id_f1(team_name):
    ensure_connection()
    query = f"SELECT team_id, team_name FROM team WHERE team_desc ='{team_name}'"
    cur = con.cursor()
    cur.execute(query)  
    results = {row[0]: row[1] for row in cur.fetchall()}
    return results

def get_team_id_db(team_name, league_id, season_id):
    """Busca team_id por nombre, liga y temporada."""
    ensure_connection()
    cur = con.cursor()
    cur.execute("""
        SELECT t.team_id FROM league_team lt
        JOIN team t ON lt.team_id = t.team_id
        WHERE lt.league_id = %s AND lt.season_id = %s AND t.team_name = %s
        LIMIT 1
    """, (league_id, season_id, team_name))
    row = cur.fetchone()
    if row:
        print(f"[DB] team_id found: {team_name} → {row[0]}")
        return row[0]
    print(f"[DB] team_id NOT FOUND: {team_name} in league {league_id}")
    return None

def get_team_id_pilot(racer_name, team_name):
    dict_team_id = get_team_id_f1(team_name)
    for team_id, complete_name in dict_team_id.items():        
        if racer_name.upper().split()[0] in complete_name.upper().split():
            return team_id

def check_team_season_duplicates(league_id, season_id, team_id):
    ensure_connection()
    query = "SELECT season_id FROM league_team WHERE league_id ='{}' AND season_id ='{}' AND team_id ='{}';".format(league_id, season_id, team_id)
    cur = con.cursor()
    cur.execute(query)  
    results = [row[0] for row in cur.fetchall()]
    return results

def check_team_player_entitiy(season_id, team_id, player_id):
    ensure_connection()
    query = """SELECT player_id FROM team_players_entity WHERE
                 season_id ='{}' AND team_id ='{}' AND player_id ='{}';""".format(season_id, team_id, player_id)
    cur = con.cursor()
    cur.execute(query)  
    results = [row[0] for row in cur.fetchall()]
    return results  

def strip_phase_suffix(name):
    """FlashScore pega la fase al título de la liga ('Liga 1 - Apertura',
    'Champions League - Play Offs'); la DB guarda el nombre base ('Liga 1').
    Recorta todo lo que sigue al primer ' - '. Seguro: ninguna liga real en la
    DB tiene ' - ' en su nombre (verificado), así que solo elimina fases."""
    return name.split(' - ')[0].strip() if name else name


def get_match_id(league_country, league_name, match_date, match_name, sport=None):
    ensure_connection()
    # FIX naming de liga: el DOM trae la fase pegada al título ('Liga 1 -
    # Apertura'); la DB guarda el nombre base. Sin recortar, el JOIN por
    # league_name fallaba y el partido salía como inexistente (afecta también
    # al flujo LIVE de milestone7/live_function que usa esta función).
    league_db = strip_phase_suffix(league_name)
    # IMPRESIÓN de verificación: palabras EXACTAS usadas en la solicitud a la DB.
    print(f"[get_match_id] country='{league_country}' | "
          f"league(DOM)='{league_name}' -> league(DB)='{league_db}' | "
          f"match_date='{match_date}' | match_name='{match_name}'"
          f"{f' | sport={sport!r}' if sport else ''}")
    # parametrizado: match.name con apóstrofe (Coquimbo~O'Higgins, M'Gladbach)
    # rompía el .format -> SyntaxError -> rollback -> devolvía None SIEMPRE, así
    # que el live nunca encontraba/actualizaba esos partidos (DB-SKIP eterno).
    #
    # FILTRO POR DEPORTE (sport, opcional): hay países con DOS ligas del mismo
    # nombre en deportes distintos (p.ej. TURKEY tiene 'Super Lig' en Basketball
    # Y en Football). Sin filtrar por deporte, get_match_id podía devolver el
    # match del deporte equivocado -> el live escribía el marcador en el partido
    # incorrecto. `sport` debe ser el NOMBRE de deporte tal cual la DB (sport.name,
    # Title Case: 'Basketball', 'Football'). Si es None -> comportamiento previo.
    params = [league_country, league_db, match_date, match_name]
    sport_join = sport_cond = ""
    if sport:
        sport_join = "JOIN sport ON sport.sport_id = league.sport_id"
        sport_cond = "and sport.name = %s"
        params.append(sport)
    else:
        # NUNCA debería ocurrir: sin deporte, una liga homónima de OTRO deporte
        # (WORLD 'World Cup' en fútbol y básquet) puede devolver el match equivocado.
        red_box_warning(
            'get_match_id llamado SIN filtro de deporte (sport=None)',
            [f"country='{league_country}'  league='{league_db}'",
             f"match='{match_name}'  date='{match_date}'",
             'Riesgo: colision cross-deporte (liga homonima). Pasar sport al caller.',
             'El proceso CONTINUA (comportamiento previo, sin filtrar deporte).'])
    query = f"""
    SELECT match.match_id
    FROM match
    JOIN league ON league.league_id = match.league_id
    JOIN country ON league.country_id = country.country_id
    {sport_join}
    WHERE country.country_name = %s and
    league.league_name = %s and
    match.match_date = %s and match.name = %s {sport_cond}"""
    try:
        cur = con.cursor()
        cur.execute(query, tuple(params))
        print("[get_match_id] búsqueda de partido ejecutada en la BD")
        res = cur.fetchone()
        if res:
            return res[0]
    except:
        con.rollback()
        return None


def get_all_match_ids(league_name, match_date, match_name, sport):
    """Como get_match_id pero SIN filtro de país y devuelve TODAS las copias.

    Pensada para torneos modelados como varias ligas HOMÓNIMAS (mismo
    league_name) en distintos países/confederaciones — caso World Cup, que en
    FlashScore aparece en las 7 confederaciones, así que el mismo partido existe
    7 veces (uno por liga). El live, al ver el partido una vez, debe actualizar
    TODAS sus copias, no solo la de un país.

    FILTRA por `sport` (Title Case DB) para NO cruzar deportes homónimos
    (World Cup de Football vs Basketball). Devuelve lista de match_id (puede
    ser vacía)."""
    ensure_connection()
    league_db = strip_phase_suffix(league_name)
    query = """
        SELECT match.match_id
        FROM match
        JOIN league ON league.league_id = match.league_id
        JOIN sport  ON sport.sport_id   = league.sport_id
        WHERE league.league_name = %s AND match.match_date = %s
          AND match.name = %s AND sport.name = %s
    """
    try:
        cur = con.cursor()
        cur.execute(query, (league_db, match_date, match_name, sport))
        return [r[0] for r in cur.fetchall()]
    except Exception:
        con.rollback()
        return []


def get_math_details_ids(match_id):
    ensure_connection()
    query = """
    SELECT match_detail_id, home FROM match_detail
     WHERE match_id = '{}';""".format(match_id);
    cur = con.cursor()
    cur.execute(query)

    dict_results = {row[0]:row[1] for row in cur.fetchall()}
    return dict_results

def get_match_ready(match_id):
    ensure_connection()
    query = "SELECT MATCH_ID FROM MATCH WHERE MATCH_ID='{}';".format(match_id)  
    cur = con.cursor()
    cur.execute(query)
    results = [row[0] for row in cur.fetchall()]
    return results

def check_match_duplicate(league_id, match_date, match_name):
    ensure_connection()
    cur = con.cursor()
    cur.execute(
        "SELECT MATCH_ID FROM MATCH WHERE LEAGUE_ID = %s AND MATCH_DATE = %s AND NAME = %s",
        (league_id, match_date, match_name)
    )
    results = [row[0] for row in cur.fetchall()]
    return results

def get_stadium_id(place_name):
    ensure_connection()
    # parametrizado: nombres con apóstrofe (Xi'an, O'Higgins) rompían el .format
    cur = con.cursor()
    cur.execute("SELECT STADIUM_ID FROM STADIUM WHERE NAME = %s", (place_name,))
    results = [row[0] for row in cur.fetchall()]
    return results

def check_stadium(stadium_id):
    ensure_connection()
    query = """SELECT STADIUM_ID FROM STADIUM WHERE stadium_id ='{}';""".format(stadium_id) 
    cur = con.cursor()
    cur.execute(query)
    results = [row[0] for row in cur.fetchall()]
    return results

def get_score_by_match_detail_id(match_detail_id):
    """Retorna el score_id si existe un registro en score_entity para el match_detail_id dado."""
    ensure_connection()
    cur = con.cursor()
    cur.execute("SELECT score_id FROM score_entity WHERE match_detail_id = %s", (match_detail_id,))
    row = cur.fetchone()
    return row[0] if row else None

def update_score(params):
    ensure_connection()
    query = "UPDATE score_entity SET points = %(points)s WHERE match_detail_id = %(match_detail_id)s"
    # query = "INSERT INTO score_entity VALUES(%(score_id)s, %(points)s, %(match_detail_id)s)"
    cur = con.cursor()
    cur.execute(query, params)
    con.commit()

def update_match_status(params):
    ensure_connection()
    query = "UPDATE match SET status = %(status)s WHERE match_id = %(match_id)s"
    cur = con.cursor()
    cur.execute(query, params)
    con.commit()

def get_match_by_day():
    ensure_connection()
    # Query to retrieve pending matches for updating.
    query = """
        SELECT sport.name, league.league_name, country.country_name,\
        match.match_date, match.start_time, match.name, match.match_id \
        FROM MATCH
        JOIN LEAGUE ON MATCH.LEAGUE_ID = LEAGUE.LEAGUE_ID
        JOIN SPORT ON SPORT.SPORT_ID = LEAGUE.SPORT_ID
        JOIN COUNTRY ON COUNTRY.COUNTRY_ID = LEAGUE.COUNTRY_ID
        WHERE MATCH.MATCH_DATE = CURRENT_DATE
        """
    # AND MATCH.STATUS = 'P' 
    cur = con.cursor()
    cur.execute(query)    
    return cur.fetchall()

def get_match_by_league_name(league_name_, month_number, day_number):
    # DEPRECATED — NO USAR: resuelve por league_name LIKE SIN país ni deporte
    # (colisiona cross-deporte: WORLD 'World Cup' fútbol/básquet). Sin llamadores.
    red_box_warning(
        'get_match_by_league_name() es DEPRECATED y resuelve SIN deporte',
        [f"league_name LIKE '{league_name_}' (sin pais ni deporte)",
         'Riesgo: colision cross-deporte. Usar un lookup con sport_id/league_id.',
         'El proceso CONTINUA.'])
    ensure_connection()
    # Query to retrieve pending matches for updating.
    query = f"""
        SELECT sport.name, league.league_name, league.league_country,
               match.match_date, match.start_time, match.name, match.match_id
        FROM MATCH 
        JOIN LEAGUE ON MATCH.LEAGUE_ID = LEAGUE.LEAGUE_ID
        JOIN SPORT ON SPORT.SPORT_ID = LEAGUE.SPORT_ID
        WHERE LEAGUE.LEAGUE_NAME LIKE '{league_name_}' AND
              MATCH.STATUS = 'P' AND
              EXTRACT(MONTH FROM match.match_date) = {month_number} AND
              EXTRACT(DAY FROM match.match_date) = {day_number}
    """ 
    cur = con.cursor()
    cur.execute(query)    
    return cur.fetchall()

def get_match_update():
    ensure_connection()
    # Query to retrieve pending matches for updating.
    query = """
        SELECT sport.name, league.league_name, league.league_country,\
        match.match_date, match.start_time, match.name, match.match_id \
        FROM MATCH 
        JOIN LEAGUE ON MATCH.LEAGUE_ID = LEAGUE.LEAGUE_ID
        JOIN SPORT ON SPORT.SPORT_ID = LEAGUE.SPORT_ID
        WHERE MATCH.MATCH_DATE <= CURRENT_DATE AND \
        START_TIME < CURRENT_TIME AND \
        MATCH.STATUS = 'P' 
        """
    try:        
        cur = con.cursor()
        cur.execute(query)    
        return cur.fetchall()
    except:
        con.rollback()


def get_match_by_league_id(league_id):
    ensure_connection()
    """
    Returns the total number of matches (int) associated with a given league_id.
    """
    query = """
        SELECT COUNT(m.match_id) AS total_matches
        FROM match AS m
        JOIN season AS s ON m.season_id = s.season_id
        WHERE s.league_id = %s
        GROUP BY s.league_id;
    """
    with con.cursor() as cur:
        cur.execute(query, (league_id,))
        row = cur.fetchone()  # fetchone() es más eficiente
        return int(row[0]) if row else 0


# ── Running leagues — control de ejecución paralela entre procesos/máquinas ────

def claim_league(league_id, section, host=None):
    """
    Reclama una liga para procesarla. Retorna True si el claim fue exitoso.
    - Nueva liga:         INSERT con status='running'
    - Liga 'interrupted': retoma desde el último checkpoint (resume)
    - Liga 'completed':   reinicia desde cero (re-ejecución habilitada)
    - Liga 'running':     otro worker la tiene → False
    """
    import socket
    ensure_connection()
    host = host or socket.gethostname()
    with con.cursor() as cur:
        cur.execute("""
            INSERT INTO running_leagues (league_id, section, host, started_at, status, current_round, current_match)
            VALUES (%s, %s, %s, NOW(), 'running', '', '')
            ON CONFLICT (league_id, section) DO UPDATE
                SET status        = 'running',
                    host          = EXCLUDED.host,
                    started_at    = NOW(),
                    current_round = CASE WHEN running_leagues.status = 'completed' THEN '' ELSE running_leagues.current_round END,
                    current_match = CASE WHEN running_leagues.status = 'completed' THEN '' ELSE running_leagues.current_match END
            WHERE running_leagues.status != 'running'
        """, (league_id, section, host))
        con.commit()
        return cur.rowcount == 1


def release_league(league_id, section, status='completed'):
    """Actualiza el status de la liga al finalizar ('completed' o 'interrupted')."""
    ensure_connection()
    with con.cursor() as cur:
        cur.execute(
            "UPDATE running_leagues SET status = %s WHERE league_id = %s AND section = %s",
            (status, league_id, section)
        )
        con.commit()


def update_league_checkpoint(league_id, section, current_round, current_match):
    """Actualiza el checkpoint de la liga tras procesar un match exitosamente."""
    ensure_connection()
    with con.cursor() as cur:
        cur.execute("""
            UPDATE running_leagues
            SET current_round = %s, current_match = %s
            WHERE league_id = %s AND section = %s
        """, (current_round, current_match, league_id, section))
        con.commit()
        # verificar que el UPDATE afectó algún registro
        if cur.rowcount == 0:
            print(f"[WARN] update_league_checkpoint: ningún registro actualizado (league_id={league_id}, section={section})")
            return False
        return True


def get_league_checkpoint(league_id, section):
    """
    Retorna (current_round, current_match, status) de la liga.
    Si no existe fila, retorna ('', '', None).
    """
    ensure_connection()
    with con.cursor() as cur:
        cur.execute(
            "SELECT current_round, current_match, status FROM running_leagues WHERE league_id = %s AND section = %s",
            (league_id, section)
        )
        row = cur.fetchone()
        return (row[0], row[1], row[2]) if row else ('', '', None)


def cleanup_stale_leagues(timeout_minutes=120):
    """
    Marca como 'interrupted' los claims huérfanos (worker caído) con más de
    timeout_minutes minutos. Preserva current_round y current_match para resume.
    """
    ensure_connection()
    with con.cursor() as cur:
        cur.execute("""
            UPDATE running_leagues
            SET status = 'interrupted'
            WHERE status = 'running'
            AND started_at < NOW() - INTERVAL '%s minutes'
        """, (timeout_minutes,))
        updated = cur.rowcount
        con.commit()
    return updated


con = getdb()