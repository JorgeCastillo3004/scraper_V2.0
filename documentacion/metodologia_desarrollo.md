# Metodología de desarrollo — scraper_V2.0

Consolida las reglas ya existentes (`DRIVER_RULES.md`, `reglas_de_desarrollo.md`,
`indicaciones_para_desarrollo.md`) + el flujo de trabajo acordado en sesión.

```
┌─ 1. ENTENDER / REUSAR ───────────────────────────────────────────────┐
│  • Leer INDICE.md → docs relevantes (código solo si hace falta)        │
│  • REUSAR funciones/bloques existentes; NO reinventar ni código nuevo  │
│  • Identificar gaps                                                    │
└───────────────────────────────┬──────────────────────────────────────┘
                                 ▼
┌─ 2. DISEÑAR + APROBAR (antes de codear) ─────────────────────────────┐
│  • Confirmar la idea EN PROSA (no usar cuadro de preguntas)           │
│  • Mostrar diagrama/resumen de la lógica                              │
│  • Discutir gaps/decisiones → ESPERAR aprobación explícita            │
└───────────────────────────────┬──────────────────────────────────────┘
                                 ▼
┌─ 3. IMPLEMENTAR ─────────────────────────────────────────────────────┐
│  DRIVER: reusar el vivo (get_driver / _reuse_driver_session).         │
│          NUNCA quit / close / kill / relanzar sin permiso EXPLÍCITO.  │
│          Si no hay driver → start_driver.py (login). Debug en 2ª tab. │
│  DB:     SOLO INSERT / UPDATE.                                        │
│          DELETE / DROP / TRUNCATE = PROHIBIDO sin confirmación por     │
│          caso (mostrar exactamente qué se borraría).                  │
│  DATOS:  resolver desde la DB (no confiar en league_id de JSON viejo).│
│          SQL parametrizado (%s) — apóstrofes (Xi'an, O'Higgins).      │
│  DOM:    esperar carga (WebDriverWait + scroll) antes de leer.        │
│  ROBUSTEZ: logs por corrida; checkpoint idempotente (retomar sin      │
│            re-procesar); NO saltar nada → flaggear pendientes FUERTE.  │
└───────────────────────────────┬──────────────────────────────────────┘
                                 ▼
┌─ 4. PROBAR (incremental, de menor a mayor riesgo) ───────────────────┐
│  a) dry-run (no escribe)        → revisar [MATCH/TEAM/DETAIL FIELDS]   │
│  b) --stop-after-first-team     → verificar UNA inserción exacta      │
│  c) --apply en 1 liga           → verificar en DB (todos los campos)  │
│  d) --apply resto               → verificar                          │
│  • Re-probar: borrar SOLO lo recién creado (con confirmación) y       │
│    re-correr (el checkpoint/anti-dup retoma donde quedó).             │
└───────────────────────────────┬──────────────────────────────────────┘
                                 ▼
┌─ 5. VERIFICAR + DOCUMENTAR ──────────────────────────────────────────┐
│  • Query READ-ONLY de integridad: match, match_detail (2x),           │
│    season, país, estadio.                                             │
│  • Actualizar documentación + INDICE.md.                              │
└──────────────────────────────────────────────────────────────────────┘
```

## Principios no negociables (resumen)
1. **Reusar antes que reinventar**; confirmar gaps y **aprobar el diseño** antes de codear.
2. **Driver**: jamás cerrarlo/matarlo/relanzarlo sin confirmación explícita en la sesión.
3. **DB**: solo INSERT/UPDATE; cualquier DELETE requiere ver el detalle exacto y aprobación puntual.
4. **Completitud**: ninguna liga/partido se ignora en silencio; lo que no se pueda
   completar se **marca fuerte** y se persiste para completarse después.
5. **Idempotencia/recovery**: checkpoint + anti-duplicado → retomar sin re-procesar
   ni duplicar.
6. **Verificar siempre en DB** lo insertado; documentar al cerrar.
