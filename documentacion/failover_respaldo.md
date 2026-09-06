# Conmutación al respaldo (SC10 + SC11)

> **La idea, en una frase:** si FlashScore deja de actualizar, que escriba SofaScore
> hasta que FlashScore vuelva.
>
> Hoy esto está **en simulación**: detecta, decide y calcula qué escribiría, pero **no
> escribe nada** en la base de datos.

---

## Las dos mitades, separadas a propósito

| Pieza | Qué hace | Archivo |
|---|---|---|
| **Detección** (SC10) | ¿el primario sigue actualizando? Solo observa | `scripts/staleness_detector.py` |
| **Decisión** (SC11) | cuándo ceder el mando y cuándo devolverlo | `scripts/failover_simulator.py` |
| Lógica común | señales y máquina de estados | `src/failover.py` |

Están separadas porque hay que **poder confiar en la detección** —verla acertar durante
días— antes de dejarle mover nada.

## Las tres señales

**A · LATIDO — ¿escribe ahora?** Se mira el `mtime` del log del live, no el heartbeat
JSON: se comprobó que `run_status_live.json` conservaba la marca del arranque **8 horas
seguidas**, así que un proceso colgado se habría visto igual que uno sano. (Arreglado en
`main2.py`: ahora late en cada ciclo; pendiente de desplegar.)

**B · COLGADOS — ¿deja partidos abiertos?** Partidos que llevan demasiado en `LIVE`. Es
la huella que dejó el incidente de los 38 días.

**C · ATRASO — ¿va por detrás del respaldo?** Partidos que SofaScore ya da por terminados
y la BD no. La señal más directa; hoy detectó 7 casos con el primario funcionando.

### Umbrales, calibrados con lo observado (no adivinados)

Un ciclo real del live tarda **134 s** y luego pausa **60 s** → ~3,2 min por vuelta.

| Umbral | Valor | Por qué |
|---|---|---|
| Latido máximo | **8 min** | ~2,5 ciclos: un ciclo lento no es una caída |
| Partido colgado | **6 h** | más que cualquier partido real de los deportes cubiertos |
| Lecturas para conmutar | **3 seguidas** | no se cede el mando por una lectura suelta |
| Lecturas para volver | **5 seguidas** | volver es más exigente que irse |

## La regla que hace que esto funcione (y que casi me como)

**Quién manda se decide por la VITALIDAD del primario, no por el veredicto global.**

Los partidos colgados son la *consecuencia* de una caída pasada y **no se arreglan
solos**: mantienen el veredicto en `WARN` indefinidamente. En la primera versión, el
respaldo tomaba el mando y **no lo devolvía jamás**, aunque el primario llevara horas
funcionando perfectamente. Lo destapó la simulación de la recuperación, no el diseño.

Ahora: el latido (y un atraso grave) deciden el mando; el resto de síntomas alertan y
pueden disparar la conmutación, pero **no impiden la vuelta**.

## Ensayo completo, con datos reales

```bash
sports_env/bin/python scripts/failover_simulator.py --reset --simular-caida --recuperar-en 5 --lecturas 11
```

```
ronda 1  ✗ STALE  vitalidad=STALE  malas=1          dueño=primario
ronda 2  ✗ STALE  vitalidad=STALE  malas=2          dueño=primario
ronda 3  ✗ STALE  vitalidad=STALE                   dueño=respaldo   ►►► CONMUTA
         ESCRIBIRÍA 15 partidos (simulado):
            BRAZIL   Bragantino~Bahia            SCHEDULED → 2-3 COMPLETED
            COLOMBIA Junior~Jaguares de Cordoba  SCHEDULED → 3-3 COMPLETED
            CHILE    U. De Chile~Coquimbo        SCHEDULED → 4-2 COMPLETED
            …
ronda 5  ! WARN   vitalidad=OK     buenas=1         dueño=respaldo   (el primario vuelve)
ronda 8  ! WARN   vitalidad=OK     buenas=4         dueño=respaldo   (aún no se lo devuelve)
ronda 9  ! WARN   vitalidad=OK                      dueño=primario   ►►► DEVUELVE EL MANDO
```

Los 15 partidos no son inventados: son partidos **realmente terminados** que la BD tiene
como `SCHEDULED` con marcador `-1`.

## Lo que falta antes de darle permiso de escritura

1. **Desplegar el arreglo del heartbeat** al servidor.
2. **Cerrar la decisión P7 — un solo escritor.** Local y servidor apuntan a la misma BD.
   El conmutador necesita un candado compartido (una fila de estado en la BD o un
   archivo que ambos respeten) que garantice que en cada momento escribe uno y solo uno.
   Sin eso, un failover automático puede **duplicar** escrituras en vez de sustituirlas.
3. **Mando manual** en los dos sentidos: la primera vez que esto salte de verdad,
   alguien va a querer decidir a mano.
4. Observar el detector unos días y comprobar que no da falsos positivos.

## Estado de los archivos

| Archivo | Contenido |
|---|---|
| `tmp/staleness_status.json` | último veredicto del detector |
| `tmp/failover_state.json` | quién manda, contadores e historial de conmutaciones |
