# Agentes y asignaciones — scraper_V2.0

> **BORRADOR (2026-06-14).** Registro de los agentes/automatizaciones del proyecto y su
> asignación (qué hace cada uno, qué lo dispara, su estado y el documento/tarea asociado).
> A revisar y completar juntos. Las filas marcadas *(a definir)* son candidatos, no decididos.

## Convenciones
- **Agente** = rutina/automatización con una responsabilidad acotada (puede ser un script, un
  watchdog del scheduler, o una tarea de Claude).
- **Estado**: `idea` · `spec` · `en desarrollo` · `activo` · `pausado`.
- **Disparador**: manual (panel/CLI) · scheduler (cada X) · evento (al terminar Y) · continuo.

## Lista de agentes

| Agente | Asignación / responsabilidad | Estado | Disparador | Documento / Tarea |
|---|---|---|---|---|
| **Agente de memoria** | Medir RAM (PSS por árbol), detectar consumidores anómalos y reducirlos (auto-stop/lightweight del driver de corrección, reaper de uvicorns) sin romper reglas del driver | `spec` | a definir (scheduler/manual) | [AGENTE_MEMORIA.md](AGENTE_MEMORIA.md) · Tarea #1 |
| Gestión de drivers (ciclo de vida) *(a definir)* | Crear/cerrar bien drivers, evitar abrir de más, idle-stop del de corrección, reaper de huérfanos | `idea` | a definir | [ESTRATEGIAS_DRIVERS_RECURSOS.md](ESTRATEGIAS_DRIVERS_RECURSOS.md) |
| Live (scores en vivo) *(a definir si se modela como agente)* | Recorrer deportes pineados, actualizar score/estado de partidos LIVE/COMPLETED; hot-reload de deportes e intervalo | `activo` | continuo (main2) | [partidos_en_vivo.md](partidos_en_vivo.md) |
| Completar faltantes (crear partidos de hoy) *(a definir)* | Barrer pineadas y crear los partidos de HOY que faltan en la BD | `activo` (manual) | manual (panel) | [PENDIENTES_FUNCIONAMIENTO.md](PENDIENTES_FUNCIONAMIENTO.md) |
| Scheduler genérico por frecuencia *(a definir)* | Ejecutar secciones (noticias, fix_team_ids, etc.) según frecuencia configurada | `idea` | scheduler | [PENDIENTES_FUNCIONAMIENTO.md](PENDIENTES_FUNCIONAMIENTO.md) |

## A completar juntos
- [ ] Confirmar qué se modela como "agente" (¿solo automatizaciones nuevas, o también los flujos existentes?).
- [ ] Por cada agente: definir disparador exacto, umbrales/parámetros, y reglas de seguridad.
- [ ] Priorizar y asignar orden de implementación.
- [ ] Vincular cada fila a su Tarea (TaskCreate) cuando se decida construirlo.
