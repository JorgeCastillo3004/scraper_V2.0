"""SC10/SC11 — Detección de obsolescencia del primario y conmutación al respaldo.

La idea, en una frase: **si FlashScore deja de actualizar, que escriba SofaScore hasta
que FlashScore vuelva**.

Este módulo contiene las dos mitades, deliberadamente separadas:

  · `evaluar_primario()`  — ¿el primario sigue actualizando? Solo observa.
  · `MaquinaFailover`     — decide CUÁNDO conmutar y cuándo volver, con histéresis.

La separación no es estética: permite confiar en la detección (verla acertar durante
días) antes de dejarle mover nada. Ninguna de las dos escribe en la base de datos.

Reglas de diseño, todas con su motivo:

1. **No se conmuta a la primera.** Un ciclo lento no es una caída. Hacen falta varias
   lecturas malas seguidas.
2. **No se vuelve a la primera.** Si el primario parpadea, alternar escritores es peor
   que quedarse en uno: hay un periodo de gracia antes de devolverle el mando.
3. **Un solo escritor.** El estado dice quién manda; nadie escribe sin ser el dueño.
"""
import os
import json
import subprocess
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ESTADO_PATH = os.path.join(ROOT, 'tmp', 'failover_state.json')

# Umbrales calibrados con el comportamiento REAL del live (2026-09-06):
# un ciclo tarda ~134 s y luego pausa 60 s → ~3,2 min por vuelta.
LATIDO_MAX_MIN = 8.0        # ~2,5 ciclos sin escribir el log = algo va mal
COLGADO_HORAS = 6.0         # un partido más de 6 h en LIVE es un partido abandonado
LECTURAS_PARA_CONMUTAR = 3  # lecturas STALE seguidas antes de ceder el mando
LECTURAS_PARA_VOLVER = 5    # lecturas OK seguidas antes de devolverlo (más exigente)


def _edad_log_minutos(servidor, ruta_remota):
    """Minutos desde la última escritura del log del live. Es la señal de vida buena:
    el heartbeat JSON conservaba la marca del arranque durante horas."""
    if servidor == 'local':
        return (datetime.now().timestamp() - os.path.getmtime(ruta_remota)) / 60.0
    out = subprocess.run(['ssh', '-o', 'ConnectTimeout=15', servidor,
                          f'date +%s; stat -c %Y {ruta_remota}'],
                         capture_output=True, text=True, timeout=40).stdout.split()
    return (int(out[0]) - int(out[1])) / 60.0


def evaluar_primario(cur, servidor='scraper_server',
                     ruta_log='/home/scraper/live_v2/logs/live_persist.log',
                     latido_max=LATIDO_MAX_MIN, colgado_horas=COLGADO_HORAS,
                     forzar_caida=False):
    """Devuelve (veredicto, señales, detalle). `cur` es un cursor abierto a la BD.
    `forzar_caida` finge que el primario está muerto, para ensayar el flujo."""
    señales, detalle = {}, {}

    if forzar_caida:
        señales['latido'] = 'STALE'
        detalle['latido'] = 'CAÍDA SIMULADA (--simular-caida)'
    else:
        try:
            edad = _edad_log_minutos(servidor, ruta_log)
            señales['latido'] = 'OK' if edad <= latido_max else 'STALE'
            detalle['latido'] = f'el live escribió su log hace {edad:.1f} min (límite {latido_max})'
        except Exception as e:
            señales['latido'] = 'DESCONOCIDO'
            detalle['latido'] = f'no se pudo comprobar ({type(e).__name__})'

    cur.execute("""
        SELECT count(*) FROM match m
         WHERE m.status = 'LIVE'
           AND (m.match_date + COALESCE(m.start_time, '00:00'::time))
               < (now() at time zone 'utc') - %s::interval
    """, (f'{colgado_horas} hours',))
    colgados = cur.fetchone()[0]
    señales['colgados'] = 'OK' if colgados == 0 else ('WARN' if colgados < 5 else 'STALE')
    detalle['colgados'] = f'{colgados} partidos llevan más de {colgado_horas} h en LIVE'

    valores = [v for v in señales.values() if v != 'DESCONOCIDO']
    veredicto = ('STALE' if 'STALE' in valores else
                 'WARN' if 'WARN' in valores else
                 'OK' if valores else 'DESCONOCIDO')
    return veredicto, señales, detalle


class MaquinaFailover:
    """Quién manda ahora y cuándo cambiar. Persiste en tmp/failover_state.json.

    Estados: `primario` (FlashScore escribe) y `respaldo` (escribiría SofaScore).
    Los contadores son los que impiden bailar: no se cambia por una lectura suelta."""

    def __init__(self, path=ESTADO_PATH, para_conmutar=LECTURAS_PARA_CONMUTAR,
                 para_volver=LECTURAS_PARA_VOLVER):
        self.path = path
        self.para_conmutar = para_conmutar
        self.para_volver = para_volver
        self.estado = self._cargar()

    def _cargar(self):
        try:
            with open(self.path, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {'dueño': 'primario', 'malas': 0, 'buenas': 0,
                    'desde': datetime.now(timezone.utc).isoformat(), 'historial': []}

    def guardar(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(self.estado, f, ensure_ascii=False, indent=2)

    @property
    def dueño(self):
        return self.estado['dueño']

    def actualizar(self, veredicto, señales=None):
        """Aplica una lectura y devuelve (dueño, evento|None).

        Quién manda se decide por la **vitalidad** del primario (¿está escribiendo
        AHORA?), no por el veredicto global. La diferencia importa: los partidos
        colgados son la CONSECUENCIA de una caída pasada y no se arreglan solos, así
        que mantienen el veredicto en WARN indefinidamente. Si se usara el veredicto
        global, el respaldo tomaría el mando y **no lo devolvería jamás**, aunque el
        primario llevara horas funcionando. Se detectó simulando la recuperación.

        Los demás síntomas sirven para alertar y para DISPARAR la conmutación, pero
        no para impedir la vuelta."""
        e = self.estado
        ahora = datetime.now(timezone.utc).isoformat()
        evento = None

        señales = señales or {}
        vitalidad = señales.get('latido', veredicto)     # sin señal, el veredicto sirve
        # un atraso grave frente al respaldo también cuenta como "no está actualizando"
        if señales.get('atraso') == 'STALE':
            vitalidad = 'STALE'

        if vitalidad == 'STALE':
            e['malas'] += 1
            e['buenas'] = 0
        elif vitalidad == 'OK':
            e['buenas'] += 1
            e['malas'] = 0

        if e['dueño'] == 'primario' and e['malas'] >= self.para_conmutar:
            e['dueño'], e['desde'], e['malas'] = 'respaldo', ahora, 0
            evento = f'CONMUTA A RESPALDO tras {self.para_conmutar} lecturas STALE seguidas'
        elif e['dueño'] == 'respaldo' and e['buenas'] >= self.para_volver:
            e['dueño'], e['desde'], e['buenas'] = 'primario', ahora, 0
            evento = f'DEVUELVE EL MANDO AL PRIMARIO tras {self.para_volver} lecturas OK seguidas'

        if evento:
            e.setdefault('historial', []).append({'cuando': ahora, 'evento': evento})
        e['ultima_lectura'] = {'cuando': ahora, 'veredicto': veredicto,
                               'vitalidad': vitalidad}
        return e['dueño'], evento
