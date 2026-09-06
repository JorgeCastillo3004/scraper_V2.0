"""Comprueba que las credenciales de Telegram funcionan. Ejecutar cuando estén puestas.

  sports_env/bin/python scripts/_debug_probar_telegram.py
"""
import sys, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'src')]
import telegram_notify as tg

print('¿credenciales cargadas?:', tg.enabled())
if not tg.enabled():
    print('\n  Faltan TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID en config.py.')
    print('  Guía: docs/telegram_setup.md')
    sys.exit(1)
ok = tg.notify('✅ Prueba de conexión del scraper.\n'
               'Si lees esto, los avisos del live están operativos.')
print('mensaje enviado:', ok)
if ok:
    print('\n  Listo. A partir de aquí llegan: arranque del live, errores de ciclo,')
    print('  relevo de navegador fallido, parada tras fallos seguidos, y los cambios')
    print('  de estado del detector (FlashScore cae / vuelve).')
