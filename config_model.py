# config.py — credenciales y configuración sensible
# Este archivo NO se sube al repositorio (.gitignore)

# Servidor remoto
SERVER_HOST = ''
SERVER_USER = ''
SERVER_PASS = ''
SERVER_PATH = '/root/scraper_v3'

# Base de datos PostgreSQL
DB_HOST     = ''
DB_NAME     = ''
DB_USER     = ''
DB_PASS     = ''

# FlashScore
FS_EMAIL    = ''
FS_PASSWORD = ''

# ── LIVE scraper ────────────────────────────────────────────────────────────
# Modo de navegador para el scraper live.
#   local   -> False (visible, para depurar)
#   servidor-> True  (headless, sin entorno gráfico)
LIVE_HEADLESS = True

# Modo de navegador para el driver de CORRECCIONES (panel Inconsistencias).
#   local    -> False (visible, para visualizar la extracción / depurar)
#   servidor -> True  (headless, sin entorno gráfico)
FIX_HEADLESS = True

# Telegram (notificaciones del live). Vacío = notificaciones deshabilitadas.
# Ver docs/telegram_setup.md para obtener token y chat_id.
TELEGRAM_BOT_TOKEN = ''
TELEGRAM_CHAT_ID   = ''
