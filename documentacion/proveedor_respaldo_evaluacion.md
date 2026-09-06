# Fuente de respaldo para el Live — evaluación de opciones

> **Qué decide este documento:** de dónde saca los datos el segundo scraper (el de
> respaldo), que escribe en la **misma `sports_db`, sin cambiar nada del esquema**, y
> que está inactivo hasta que el primario (FlashScore) se queda sin actualizar.
>
> Corresponde al item **SC4/SC5** del `ROADMAP_SCRAPER.md`.
> Todo lo de aquí está **verificado el 2026-09-06** ejecutando las APIs y leyendo la
> documentación vigente de cada proveedor — ningún dato viene copiado del roadmap.

---

## 1. Qué hay que cubrir (dato real, no lista de marketing)

De la BD en producción: **114 ligas registradas, 77 con partidos, 10.416 partidos.**

| Deporte | Ligas | Partidos |
|---|---:|---:|
| Football | 49 | 7.302 |
| Baseball | 8 | 1.040 |
| Hockey | 14 | 879 |
| Basketball | 14 | 755 |
| American Football | 2 | 372 |
| Tennis | 11 | 64 |
| Boxing | 6 | 2 |
| Motor Sport | 1 | 2 |
| Golf | 9 | 0 |

Dos consecuencias que mandan sobre la decisión:

1. **El fútbol es el 70 % del volumen**, pero un proveedor *solo de fútbol* deja fuera
   3.000 partidos y 5 deportes.
2. **El béisbol es el punto duro**: los 1.040 partidos no son de la MLB, sino de
   **NPB (Japón), KBO (Corea), LMB (México), LIDOM (Dominicana) y LBPRC (Puerto Rico)**.
   Es justo lo que los proveedores internacionales suelen no cubrir.

## 2. Criterios, en el orden de peso

> **Prioridad fijada por Jorge (2026-09-06):** manda la **cantidad de datos**,
> **conservando la base de datos actual**, y aplicado **primero a la sección Live**;
> el resto de secciones (fixtures, noticias, jugadores) se expande después.
> Esto reordena el criterio 4 del roadmap: "ser API HTTP" deja de ser eliminatorio y
> pasa a ser una ventaja de robustez, no un requisito.

1. **Cobertura**: cuántas de las ligas que ya están en la BD trae, y cuántos partidos.
2. Que sirva para el **Live**: marcador y estado en tiempo real, no diferido.
3. Que encaje **sin tocar la BD**: mismos `match_id`, mismos equipos, mismas tablas.
4. Resultados finales a tiempo para cerrar el mismo día.
5. Coste al volumen real (un respaldo en espera consume casi nada).
6. Que falle de forma **independiente** del primario (deseable, no excluyente).
7. Estabilidad de sus identificadores (determina el trabajo de la capa de mapeo).

---

## 3. Las opciones

### 🟢 ESPN (API pública no oficial) — *el mejor candidato hoy*

**Ventajas**
- **Cubre los 9 deportes** del scraper con un endpoint por liga.
- **Sin registro, sin key, sin coste.** Nada que renovar ni que caduque.
- **Muy rápida**: ~90 ms por respuesta, JSON limpio y estructurado.
- Trae exactamente lo que el live necesita: equipos, marcador, estado
  (`SCHEDULED`/`IN_PROGRESS`/`FINAL`), reloj, periodo y fecha UTC.
- **Cubre las ligas latinoamericanas**, que es donde más se sufre: verificadas Ecuador,
  Perú, Colombia, Chile, Bolivia, Argentina, Brasil y China.
- **88 % de los nombres de equipo cruzan** con la BD (136 evaluados, 120 cruzan). Los
  fallos son todos el mismo patrón —abreviatura contra nombre completo: "Argentinos Jrs"
  vs "Argentinos Juniors", "A. Italiano" vs "Audax Italiano"— así que un diccionario de
  abreviaturas lo lleva cerca del 100 %.
- Es **API HTTP pura**: cumple el criterio 4 sin discusión, y sigue funcionando aunque
  el navegador del scraper esté caído.

**Límites**
- **No cubre NPB, KBO, LMB ni LIDOM** (HTTP 400): **1.040 partidos de béisbol sin respaldo**.
- Es una API *no oficial*: no hay contrato ni SLA, y puede cambiar sin aviso.
- Rareza verificada: **devuelve 403 si se mandan cabeceras de navegador** y 200 al
  cliente HTTP pelado. Hay que no disfrazarse de navegador.

### 🟡 API-Sports / API-Football — *el que puede tapar el hueco*

**Ventajas**
- **Una API por deporte** (football, baseball, basketball, hockey, NFL, F1, MMA…): es el
  único candidato de pago que cubre los 9 deportes del scraper.
- **Plan gratuito permanente: 100 peticiones/día por API, sin tarjeta.** Para un respaldo
  en espera —que casi no consume hasta activarse— puede ser suficiente.
- Barato al escalar: los planes de pago arrancan en torno a **10-19 USD/mes**.
- Producto comercial con documentación y soporte: identificadores estables y contrato,
  al contrario que ESPN.

**Límites**
- **Falta verificar si cubre NPB/KBO/LMB/LIDOM**, que es la única razón de peso para
  elegirlo sobre ESPN. Sin eso confirmado, no aporta nada que ESPN no dé gratis.
- 100 req/día **no alcanzan** si el respaldo se activa de verdad (un ciclo por minuto son
  ~1.440): al promocionarse habría que pagar plan.
- Requiere gestionar una credencial (renovación, rotación, y no filtrarla al repo).

*Para cerrarlo:* `scripts/_debug_evaluar_proveedor_apisports.py` ya está escrito; mide su
cobertura real contra las 77 ligas de la BD. Solo necesita una key gratuita de
`dashboard.api-football.com/register`.

### 🟢 SofaScore — *la que más datos trae* (medido)

**Ventajas — con la cobertura ya medida contra la BD (2026-09-06)**

| Deporte | Ligas en la BD | Cubiertas | % partidos |
|---|---:|---:|---:|
| American Football | 2 | 2 | **100 %** |
| Baseball | 8 | 8 | **100 %** |
| Football | 42 | 39 | **95 %** |
| Hockey | 8 | 7 | **96 %** |
| Basketball | 13 | 7* | 27 %* |
| Tennis | 2 | 0* | 0 %* |
| **TOTAL medido** | **75** | **63** | **91 %** |

\* **Falsos negativos del método**, no ausencias: el cruce se hizo por país y esas
competiciones no cuelgan de un país. Verificado uno por uno con su buscador:
Euroleague, Eurocup y FIBA EuroBasket existen bajo la categoría **"International"**;
Roland Garros y Wimbledon bajo **ATP/WTA**; la QSL de Qatar es **"Stars League [Qatar]"**
y la LPF de Panamá es **"Liga Panameña de Fútbol, Apertura/Clausura"**. Contando esos,
la cobertura real sube a **~74 de 75 ligas (99 %)**; el único caso sin confirmar es la
Jupiler Pro League belga (197 partidos), que probablemente esté con otro nombre.

- **Cubre el 100 % del béisbol**, que es exactamente el hueco de ESPN: NPB, KBO, LMB,
  LIDOM, LBPRC, LVBP y MLB. Verificado en vivo ("Professional Baseball, Central League").
- **Volumen muy superior al que hoy se sigue**: en una foto cualquiera ofrecía
  **271 partidos en vivo repartidos en 329 ligas simultáneas**, frente a las 77 ligas que
  tiene la BD entera. Margen de sobra para expandir después a más competiciones.
- JSON estructurado, sin parsear DOM, con marcador, estado, reloj y torneo.
- Funciona **reutilizando el navegador que el scraper ya tiene abierto**: no hace falta un
  segundo Firefox ni credenciales.

**Límites**
- **Bloquea todo cliente HTTP con 403**: sin cabeceras, con User-Agent de navegador, con
  Origin/Referer, en `api.sofascore.com`, en `www.sofascore.com` y en `.app`. Solo
  responde desde un navegador real (`fetch` dentro de la página, que sí funciona).
- Por tanto **no es independiente del primario**: si el fallo es el driver —snap roto,
  geckodriver, login—, caen los dos a la vez. Cubre el fallo "FlashScore cambió el DOM o
  bloquea al scraper", que es el más frecuente, pero no el fallo del navegador.
- Sus endpoints cambian sin aviso: `scheduled-events/{fecha}` ya devuelve 404;
  `events/live` sigue vivo. Conviene aislar las rutas en un módulo.
- Los nombres de liga **no coinciden** con los de la BD (Roland Garros vs "WTA French
  Open", Stars League vs "QSL"): el trabajo real está en la capa de mapeo, no en leer.

### 🔴 football-data.org — descartado (doble motivo)

Gratis son **12 competiciones**: Champions, Premier, Bundesliga, LaLiga, Serie A, Ligue 1,
Eredivisie, Primeira Liga, Championship, Brasil Serie A, Mundial y Eurocopa. **De las tuyas
solo coincide Brasil Serie A.** Y el plan gratuito entrega **"scores delayed"**, lo que
choca de frente con el criterio 2 (cierre el mismo día). Solo fútbol. 10 req/min.

### 🔴 SportMonks — descartado

Cubre **fútbol, cricket y F1**: deja fuera **béisbol, baloncesto, hockey y am. football**,
5 de tus 9 deportes. El plan gratuito son **2 ligas** (danesa y escocesa). Desde 29 €/mes.

### 🔴 TheSportsDB — descartado

Con la key pública de prueba su API devuelve **5 ligas en total**, ninguna de las tuyas: ni
NPB, ni KBO, ni LMB, ni las sudamericanas. Su cobertura real está tras el plan de pago.

---

## 4. Comparativa

| | Deportes cubiertos | Ligas LatAm | Béisbol asiático/caribeño | API HTTP | Coste |
|---|---|---|---|---|---|
| **ESPN** | 9/9 | ✅ | ❌ | ✅ | gratis |
| **API-Sports** | 9/9 | por verificar | **por verificar** | ✅ | gratis / ~10-19 USD |
| **SofaScore** | 9/9 | ✅ | ✅ | ❌ (navegador) | gratis |
| football-data.org | 1/9 | ❌ | ❌ | ✅ | gratis (con retraso) |
| SportMonks | 4/9 | ❌ | ❌ | ✅ | 29 €/mes |
| TheSportsDB | — | ❌ | ❌ | ✅ | de pago |

## 5. Recomendación (con el criterio de máxima cantidad de datos)

**SofaScore como fuente principal del respaldo del Live.** Es la única que cubre
**~99 % de las ligas y el 100 % del béisbol**, que es donde ESPN falla, y trae mucho más
de lo que hoy se sigue (329 ligas en vivo simultáneas frente a 77 en la BD), lo que deja
margen para la expansión posterior a otras secciones. Ya está probado que funciona con el
driver actual, sin segundo navegador ni credenciales.

**ESPN como segunda red, precisamente porque falla distinto.** No la sustituye: la
complementa. Si el problema es que el navegador no levanta —el fallo más incómodo, porque
tumba también a SofaScore—, ESPN sigue respondiendo por HTTP puro sin navegador, y cubre
los 9 deportes y las ligas latinoamericanas con un 88 % de cruce de nombres.

**API-Sports queda como plan de pago** si algún día se quiere un proveedor con contrato y
SLA. Hoy no aporta nada que SofaScore no dé con mejor cobertura y gratis; solo tendría
sentido si se exige un acuerdo formal.

### El trabajo real no es leer, es mapear

Las tres fuentes dan los datos; ninguna usa los nombres de la BD. "Roland Garros, Women"
es "WTA French Open"; "Stars League" es "QSL"; "Argentinos Juniors" es "Argentinos Jrs".
Por eso el orden correcto es **primero la capa de mapeo (SC6) y después la ingesta**: con
el mapeo resuelto, cambiar de proveedor es cuestión de un módulo, y sin él, cualquier
proveedor escribe en el partido equivocado — que es el único error verdaderamente caro,
porque corrompe en silencio las apuestas que cuelgan de ese partido.

## 6. Lo que no cambia en ningún escenario

La base de datos. El respaldo produce el mismo diccionario de resultados que hoy produce
`live_function.py` y escribe por las mismas tres funciones —`get_match_id`,
`update_score`, `update_match_status`—, así que **el esquema, los identificadores y las
apuestas que cuelgan de ellos no se tocan**. Lo único nuevo es la capa de traducción de
nombres, que es el trabajo real (SC6).

---

## 7. Convalidación en vivo — FÚTBOL (2026-09-06, sin escribir en la BD)

Primera prueba real del proveedor, con **driver propio e independiente** (no toca el del
panel ni el del live) y **cero escrituras**: `scripts/live_sofascore_futbol.py` sobre
`src/sofascore_provider.py`.

**Resultado: 4 de 4 partidos que la BD tenía en vivo fueron localizados en SofaScore.**

| Comprobación | Resultado |
|---|---|
| Hora de inicio | **0 minutos de diferencia** en los 4 (11:00, 11:35, 11:35, 12:00 UTC) |
| Fecha | idéntica en los 4 |
| Marcador | idéntico salvo uno, y por buen motivo (ver abajo) |
| Estado | LIVE = LIVE en los 4 |
| Liga | `China/Chinese Super League` ↔ `CHINA/Super League` (cruza, nombre distinto) |
| Nombre del partido | **ninguno idéntico**: siempre hay variante |

### Lo que enseñó la prueba

**1. El nombre del equipo NO sirve como clave, la hora SÍ.** Ninguno de los 4 partidos
tenía el nombre igual en ambas fuentes: `Chongqing Tonglianglong FC` vs
`Chongqing Tonglianglong`, `Henan FC` vs `Henan Songshan Longmen`, `Zhejiang` vs
`Zhejiang Professional`. En cambio la **hora de inicio coincidió al minuto exacto en los
cuatro**. Por eso el emparejador va en dos pasos: primero por nombre normalizado y, si
falla, por **fecha+hora exacta** dentro de la liga, aceptando solo si hay un único
candidato que además comparte alguna palabra del nombre. Eso subió el acierto de **2/4 a
4/4** sin inventar nada.

**2. Un "marcador distinto" que en realidad es la prueba de que el respaldo sirve.**
En `Yunnan Yukun ~ Liaoning Tieren`, SofaScore daba 2-0 y la BD 1-0: no es un error, es
que **SofaScore vio el gol antes**. La BD se actualiza con el ciclo del live (~60 s), así
que un desfase de segundos es normal — y demuestra que la segunda fuente aporta.

**3. Cobertura confirmada al 100 %.** Los 4 partidos en vivo de la Super League china
estaban en la BD. Los otros 3 partidos chinos en vivo eran de `Chinese League 1`
(segunda división), que la BD no sigue: correcto que no crucen.
Además se resolvió el único hueco que quedaba de la sección 3: la **Jupiler Pro League
belga sí está**, como `Pro League [Belgium]` → la cobertura es **75 de 75 ligas**.

### Errores propios que la prueba destapó (ya corregidos)

- Leer el marcador de la BD con `ORDER BY match_detail_id` **invierte el resultado**: el
  id es un UUID y ordena alfabéticamente. Hay que ordenar por `match_detail.home DESC`.
  Con la consulta mal, los marcadores parecían invertidos y no lo estaban.
- Cruzar ligas por igualdad exacta da 0 coincidencias: `Chinese Super League` nunca será
  `Super League`. Hace falta coincidencia parcial **anclada al país**, o un alias explícito.

### Siguiente paso

Extender a **Basketball** y **Baseball** (el script ya acepta `--deporte`), y construir el
diccionario de alias de ligas y equipos que salga de estas corridas: es la capa de mapeo
del SC6, y es lo único que separa esto de un respaldo funcional.
