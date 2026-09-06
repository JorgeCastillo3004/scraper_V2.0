"""
telegram_notify.py
==================
Notificaciones del scraper LIVE vía Telegram Bot API.

- notify(text)        : envía un mensaje (alerta de problema o latido OK).
- build_hourly_summary(matches_by_sport) : arma el texto del resumen horario
  (agrupado por deporte; por partido: home, score home, visitante, score
  visitante).

Si TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID están vacíos en config.py, las
notificaciones quedan deshabilitadas (no-op) y se registra en consola.
Ver docs/telegram_setup.md para obtener token y chat_id.
"""

import requests

try:
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
except Exception:  # config sin los campos (entornos viejos)
    TELEGRAM_BOT_TOKEN = ''
    TELEGRAM_CHAT_ID = ''

_API = 'https://api.telegram.org/bot{token}/sendMessage'


def enabled():
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def notify(text):
    """Envía `text` por Telegram. Devuelve True si se envió, False si no."""
    if not enabled():
        print(f'[TELEGRAM disabled] {text.splitlines()[0] if text else ""}')
        return False
    try:
        resp = requests.post(
            _API.format(token=TELEGRAM_BOT_TOKEN),
            data={'chat_id': TELEGRAM_CHAT_ID, 'text': text,
                  'disable_web_page_preview': True},
            timeout=15,
        )
        ok = resp.status_code == 200 and resp.json().get('ok', False)
        if not ok:
            print(f'[TELEGRAM error] status={resp.status_code} body={resp.text[:200]}')
        return ok
    except Exception as e:
        print(f'[TELEGRAM exception] {type(e).__name__}: {e}')
        return False


def build_hourly_summary(matches_by_sport, header='✅ LIVE OK — resumen última hora'):
    """
    matches_by_sport: dict {sport_name: [match_info, ...]} ya deduplicado
    (último resultado por partido). Devuelve el texto del resumen.
    """
    lines = [header]
    total = 0
    if not matches_by_sport:
        lines.append('(sin partidos en la última hora)')
    for sport, matches in matches_by_sport.items():
        lines.append('')
        lines.append(f'— {sport} ({len(matches)}) —')
        for m in matches:
            total += 1
            lines.append(f'{m["home"]} {m["home_result"]} - '
                         f'{m["visitor_result"]} {m["visitor"]}')
    lines.insert(1, f'Total partidos: {total}')
    return '\n'.join(lines)
