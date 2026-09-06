#!/usr/bin/env python3
"""
DEBUG — por qué un match no se encuentra en scan_results_page.
Compara el nombre que usa el DB para buscar vs el texto real de la fila
en FlashScore (driver vivo). No toca la DB.
"""
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'src'))

from selenium.webdriver.common.by import By
from scripts.driver_session import get_driver

# misma normalización que scan_results_page._norm_team
def _norm_team(s):
    return s.lower().replace('-', '').replace(' ', '')

XPATH_ROWS = '//div[contains(@class,"leagues--static event--leagues")]/div'

DB_NAME = "Lokomotiv Moscow~Krasnodar"   # exactamente como está en la DB
home, _, visitor = DB_NAME.partition('~')
h_norm, v_norm = _norm_team(home), _norm_team(visitor)

print('=' * 78)
print('DB busca   home=%r  visitor=%r' % (home, visitor))
print('DB norm    h=%r  v=%r' % (h_norm, v_norm))
print('=' * 78)

driver = get_driver()
print('current_url:', driver.current_url)
rows = driver.find_elements(By.XPATH, XPATH_ROWS)
print('filas totales en página:', len(rows))

candidatos = 0
for i, row in enumerate(rows):
    try:
        text = row.text or ''
    except Exception:
        text = ''
    tn = _norm_team(text)
    # candidato si menciona cualquiera de los dos equipos
    if 'krasnodar' not in tn and 'lokomotiv' not in tn:
        continue
    candidatos += 1
    try:
        html = row.get_attribute('outerHTML') or ''
    except Exception:
        html = ''
    has_tip = 'Click for details!' in html or 'Click for match detail!' in html
    print('\n' + '-' * 78)
    print('FILA #%d' % i)
    print('row.text (repr)      : %r' % text)
    print('text_norm            : %r' % tn)
    print('has_tip (clickable)  : %s' % has_tip)
    print('h_norm in text_norm  : %s   (%r)' % (h_norm in tn, h_norm))
    print('v_norm in text_norm  : %s   (%r)' % (v_norm in tn, v_norm))
    # ¿matchearía scan_results_page? (ambos + has_tip)
    matchea = (h_norm in tn) and (v_norm in tn) and has_tip
    print('>>> scan_results_page lo tomaría: %s' % matchea)

print('\n' + '=' * 78)
print('candidatos (mencionan algún equipo): %d' % candidatos)
print('[done] driver vivo intacto.')
