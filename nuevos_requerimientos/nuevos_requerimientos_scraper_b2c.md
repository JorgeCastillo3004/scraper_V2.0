# Nuevos requerimientos — Scraper B2C
### Manejo centralizado de scripts vía frontend + API

> **Estado del documento:** borrador inicial basado en indicaciones verbales.
> Las secciones marcadas como **[POR DEFINIR]** son brechas que deben resolverse
> antes de implementar. Verificar contra el `índice` existente para evitar
> duplicar o contradecir lo ya definido.

---

## 1. Contexto

Ya existe un conjunto de scripts de scraping desarrollados. El objetivo de esta
fase **no** es reescribirlos, sino integrar un **control centralizado** sobre
ellos a través de un frontend que se comunica con una API. El trabajo consiste
en ajustes y completar la orquestación, no en desarrollo desde cero.

Arquitectura general: **Frontend → API → control de los scripts (módulos).**

---

## 2. Módulos y su comportamiento esperado

### 2.1. Módulo Live
- Debe ejecutarse **de forma permanente en background**.
- Sigue corriendo **aunque el frontend esté cerrado**; no depende de que haya
  una sesión de UI abierta.
- Debe arrancar/seguir activo cada vez que el sistema se conecta.
- Cuando **no consigue partidos** o tiene dificultad para **crear o actualizar**
  partidos, registra la **liga afectada** en un archivo de incidencias.

### 2.2. Módulo Inconsistencias
- Se ejecuta **automáticamente**, no manualmente.
- **Detecta** las ligas/partidos que Live marcó como problemáticos (leyendo el
  archivo que Live escribe).
- Procede a **completar la data faltante** de esas ligas/partidos.

### 2.3. Módulo Noticias
- Se ejecuta **automáticamente, al menos una vez al día**.
- La **frecuencia es configurable desde el frontend** (puede ser en horas).
- Debe correr siempre, de forma automática, independientemente de la UI.

---

## 3. Tareas a realizar (una a una)

1. **Verificar el `índice`** de la documentación existente e identificar qué de
   lo aquí descrito ya está cubierto y qué entra en conflicto con lo modificado
   recientemente.
2. **Definir el mecanismo de ejecución permanente de Live** (ver brecha 5.1).
3. **Definir el contrato del archivo de incidencias** que escribe Live y lee
   Inconsistencias (ver brecha 5.2).
4. **Implementar el disparo automático de Inconsistencias** a partir de ese
   archivo (ver brecha 5.3).
5. **Implementar el scheduler de Noticias** con frecuencia configurable desde
   el frontend (ver brecha 5.4).
6. **Definir cómo el frontend/API controla cada módulo** (start/stop/estado,
   cambio de frecuencia) (ver brecha 5.5).
7. **Definir manejo de fallos y reinicio** de cada proceso (ver brecha 5.6).
8. Integrar todo y validar el flujo completo de punta a punta.

---

## 4. Resumen del flujo

```
        ┌─────────────┐
        │  Frontend   │  (control: start/stop, frecuencias, estado)
        └──────┬──────┘
               │ API
        ┌──────┴──────────────────────────────────┐
        │                                          │
   ┌────▼────┐      escribe        ┌───────────────▼──┐
   │  LIVE   │ ── incidencias ───► │  archivo de       │
   │ (always)│                     │  inconsistencias  │
   └─────────┘                     └────────┬──────────┘
                                            │ lee/detecta
                                   ┌────────▼────────┐
                                   │ INCONSISTENCIAS │ ► completa data faltante
                                   └─────────────────┘

   ┌──────────┐
   │ NOTICIAS │ ► corre ≥1 vez/día, frecuencia configurable
   └──────────┘
```

---

## 5. Brechas por definir antes de implementar

> Estas son las preguntas abiertas. Cada una bloquea una o más tareas del punto 3.

**5.1. Ejecución permanente de Live — [POR DEFINIR]**
- ¿Quién garantiza que Live siempre corre? ¿Process manager externo
  (systemd / Supervisor / pm2), un contenedor con `restart: always`, o lógica
  embebida en la propia app?
- ¿Qué pasa si el proceso cae: reinicio automático, alerta, ambos?

**5.2. Contrato del archivo de incidencias — [POR DEFINIR]**
- Formato: ¿JSON, JSONL, CSV, log plano?
- ¿Qué campos? (p. ej. liga, tipo de problema, timestamp, estado
  pendiente/procesado).
- ¿Un archivo único acumulativo, uno por día, o una cola?
- ¿Cómo se evita condición de carrera si Live escribe mientras Inconsistencias
  lee? (lock, rename atómico, append-only).

**5.3. Disparo de Inconsistencias — [POR DEFINIR]**
- ¿Cómo se entera de que hay algo nuevo: polling cada X tiempo, watcher de
  archivo (inotify), o cola de mensajes?
- ¿Marca cada incidencia como "procesada" para no repetir trabajo?

**5.4. Scheduler de Noticias — [POR DEFINIR]**
- ¿La frecuencia configurada en el frontend se aplica en tiempo real o requiere
  reinicio del scheduler?
- ¿Dónde se persiste esa configuración (BD, archivo de config)?
- ¿Qué herramienta de scheduling: cron, APScheduler, Celery beat?

**5.5. Control desde frontend/API — [POR DEFINIR]**
- ¿Qué acciones expone la API por módulo? (start, stop, restart, estado,
  set-frecuencia).
- ¿Cómo se reporta el estado de cada módulo a la UI (corriendo / detenido /
  con errores)?

**5.6. Manejo de fallos y observabilidad — [POR DEFINIR]**
- Estrategia de logs por módulo.
- ¿Hay monitoreo/alertas (recordando que ya usas Grafana en otros proyectos)?

---

## 6. Siguiente paso recomendado

Resolver primero **5.2** (contrato del archivo de incidencias), porque es el
punto de acople entre Live e Inconsistencias y condiciona 5.3. El resto puede
definirse en paralelo.
