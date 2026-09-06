# Sistema MCP ↔ RAG (Variante B: con vectores + embeddings locales)

> **Estado: DISEÑO a revisar (2026-06-15).** Documento para leer con detenimiento antes de
> implementar. Describe cómo Claude Code se conecta al `rag_system` a través de un servidor
> **MCP** local, usando **embeddings locales** (sin OpenAI ni keys externas) para habilitar
> búsqueda semántica por vectores. No hay código todavía; esto es el plano.

---

## 1. Objetivo

Que **cada vez que Claude trabaje en una tarea**, recupere del RAG **solo el contexto
necesario** (recuperación granular) y, tras un cambio, **sincronice** de vuelta la entidad
afectada — todo a través de un **servidor MCP local**, **sin depender de OpenAI** ni de
ninguna key de acceso de terceros.

**Variante B** = se habilita la **búsqueda semántica por vectores** (`/api/search/`),
generando los embeddings con un **modelo local** que corre offline en la máquina.

Principio rector (no cambia): **la verdad es el código + la BD + `documentacion/` (git);
el RAG es un ÍNDICE DERIVADO de eso.** El RAG son los planos; `sports_db` es lo que existe.
Claude **verifica lo recuperado contra la realidad antes de actuar.**

---

## 2. Arquitectura (capas)

```
   FUENTE DE VERDAD                          ÍNDICE DERIVADO            CABLE        INTELIGENCIA
   ────────────────                          ───────────────           ─────        ────────────
   código (src/, api/, frontend/)  ─┐
   pestañas del panel               │  indexa   ┌───────────────┐   herramientas  ┌────────────┐
   documentacion/*.md (git)         ├─────────► │  rag_system    │ ◄──MCP local──► │ Claude Code │
   esquema sports_db                │           │  (project 5)   │   (stdio)       │  (terminal) │
   sprints / requerimientos        ─┘           │  + pgvector    │                 └────────────┘
                                                 │  + EMBEDDER    │
                                                 │    LOCAL       │
                                                 └───────────────┘
```

- **Claude Code** = cliente MCP. Ya está autenticado con tu sesión → **no necesita keys**.
  Nunca genera ni ve embeddings; solo llama herramientas y recibe texto.
- **Servidor MCP** = adaptador local que traduce herramientas MCP ↔ API REST del RAG.
- **rag_system** = el almacén/índice (Postgres + pgvector). Aquí — y SOLO aquí — viven los
  embeddings.
- **Embedder local** = modelo de embeddings que corre en la máquina (reemplaza a OpenAI).

---

## 3. Componentes

### 3.1 rag_system (EXISTENTE)
- API: `http://localhost:8001` (docs en `/docs`). Frontend `:3001`. Guía: `~/work/rag_system/rag_inicio.md`.
- Este proyecto ya está registrado como **project 5** (scraper_V2.0).
- Modelo de entidades: **Projects → Screens → Modules → Classes → Functions + Requirements + Documents.**
- Endpoints clave:
  - `GET/POST/PATCH/DELETE /api/projects/`
  - `GET/POST/PATCH/DELETE /api/{entity}/` (screens, modules, classes, functions, requirements)
  - `POST /api/documents/` `{project_id, title, content, doc_type}` — auto-chunk ~1500 chars (overlap 150). `doc_type`: architecture | api_spec | schema | requirements | other
  - `POST /api/search/` `{query, project_id?, top_k?}` — **semántica, SIN LLM** (devuelve entidades + chunks rankeados). ← **el endpoint que usa vectores**
  - `POST /api/ask/` `{query, project_id?, top_k?}` — search + Claude redacta respuesta. **NO usar para el agente** (sería Claude llamando a Claude). `ask` es para que un humano pregunte.
- Campo `embedding_ready: true` = entidad indexada y buscable.
- **Estado actual del bloqueo:** los embeddings hoy están **detenidos** porque `OPENAI_API_KEY`
  es un placeholder en el `.env` del RAG. La Variante B lo resuelve cambiando el backend a local
  (ver §4).

### 3.2 Servidor MCP (NUEVO — a construir)
- Programa local que se lanza como subproceso de Claude Code (transporte **stdio**).
- Expone **herramientas** (§5). Internamente hace requests HTTP a `localhost:8001`.
- Sin estado propio; no guarda secretos; no toca `sports_db` directamente.
- Puede vivir en `~/work/rag_system/` (es infra del RAG, agnóstica al proyecto) o en un
  `mcp/` dedicado. **A decidir** (ver §10).

### 3.3 Embedder local (NUEVO — reemplaza OpenAI)
- Modelo de embeddings que corre offline, sin key. Candidatos (a elegir, §10):
  - `sentence-transformers` con `BAAI/bge-small-en-v1.5` (384 dims, liviano) o
    `bge-base-en-v1.5` (768 dims) — buen costo/calidad, multilingüe limitado.
  - `nomic-embed-text` (768 dims) — fuerte, corre local (p.ej. vía Ollama).
  - Multilingüe (los nombres de equipos/ligas son ES/EN/varios): considerar
    `intfloat/multilingual-e5-base` (768 dims).
- **Dónde se integra:** dentro del **rag_system**, no en el MCP. El RAG llama al embedder en
  dos momentos (§6). Cambiar de OpenAI a local es un **cambio de código en rag_system**
  (VERIFICAR dónde: buscar la función que hoy llama a OpenAI para `create/update` y para
  `/api/search/`).

### 3.4 Claude Code (cliente MCP)
- Se registra el servidor MCP en su config (`.mcp.json` / settings) — ver §7.

---

## 4. Embeddings locales — el cambio central de la Variante B

Hoy el RAG embebe con OpenAI. Para la Variante B hay que **sustituir el backend de embeddings
por uno local**. Implica:

1. **Elegir el modelo** (§3.3) y fijar su **dimensión de vector** (p.ej. 384 o 768).
2. **Ajustar la columna pgvector** al número de dimensiones del modelo elegido. ⚠️ Si la
   columna fue creada con la dimensión de OpenAI (1536), **no coincide** con un modelo local de
   384/768 → hay que migrar la columna (o crear una nueva) a la dimensión correcta.
3. **Re-embeber lo ya cargado:** los vectores viejos (si los hubiera, de OpenAI) **no son
   comparables** con los nuevos. Hay que regenerar embeddings de todas las entidades/chunks con
   el modelo local. (En este proyecto el bloqueo significaba que casi nada está embebido aún, así
   que el costo de re-embeber es bajo — VERIFICAR cuántas entidades tienen `embedding_ready`.)
4. **Regla de oro:** el **MISMO modelo** debe usarse al escribir (indexar) y al leer (consultar).
   Si cambiás el modelo en el futuro, hay que re-embeber todo otra vez.

> Esto es un cambio acotado y reversible: solo afecta *cómo* el RAG produce el vector, no el
> resto de su API. El servidor MCP y Claude Code no se enteran.

---

## 5. Herramientas que expone el servidor MCP

| Herramienta MCP | Parámetros | Endpoint RAG que envuelve | ¿Usa embeddings? |
|---|---|---|---|
| `rag_search` | `query`, `top_k?` | `POST /api/search/` (project_id=5 fijo) | **SÍ (lectura)** |
| `rag_get_function` | `name` o `id` | `GET /api/functions/?project_id=5&...` | No |
| `rag_list_modules` | — | `GET /api/modules/?project_id=5` | No |
| `rag_get_document` | `title` o `id` | `GET /api/documents/?project_id=5&...` | No |
| `rag_list_requirements` | `status?` (pending/in_progress/done) | `GET /api/requirements/?project_id=5&...` | No |
| `rag_upsert_function` | campos de function | `POST`/`PATCH /api/functions/` | No (pero **dispara re-embed** en el RAG) |
| `rag_upsert_document` | `title, content, doc_type` | `POST`/`PATCH /api/documents/` | No (dispara re-embed) |
| `rag_upsert_requirement` | `title, description, status, priority` | `POST`/`PATCH /api/requirements/` | No (dispara re-embed) |

Notas:
- Todas fijan `project_id=5` por dentro (el agente no tiene que recordarlo).
- Las de **lectura estructurada** (`get_*`, `list_*`) **no** usan vectores: son SQL normales.
- Solo `rag_search` consulta vectores. Las `upsert_*` no embeben *en el momento de la
  herramienta*, pero **provocan** que el RAG embeba en background (§6, momento de escritura).
- **NO** se expone una herramienta que llame `/api/ask/` (evitar Claude→Claude).
- Para crear requirements nuevos, respetar el **WORKFLOW OBLIGATORIO** de `rag_inicio.md`
  (borrador → aprobación explícita → migración): el MCP no debe escribir requirements directo
  sin ese flujo.

---

## 6. En qué punto EXACTO se usan los embeddings (los dos momentos)

Los embeddings se usan **únicamente dentro del RAG**, para alimentar `/api/search/`. Dos momentos:

**(1) Al ESCRIBIR / indexar** — cuando `rag_upsert_*` crea o actualiza una entidad/documento:
- El RAG toma el texto (para documents: cada chunk de ~1500 chars), lo pasa por el **embedder
  local**, y guarda el vector en pgvector. Marca `embedding_ready=true` al terminar.

**(2) Al LEER / consultar** — cuando `rag_search` llama `/api/search/`:
- El RAG embebe la **query** con el **mismo embedder local**, y hace nearest-neighbor en pgvector
  contra los vectores guardados. Devuelve los top_k más parecidos (entidades + chunks).

```
ESCRITURA:  texto/chunk ──[embedder local]──► vector ──► pgvector   (embedding_ready=true)
LECTURA:    query       ──[embedder local]──► vector ──► kNN en pgvector ──► top_k resultados
            (MISMO modelo en ambos lados, o los vectores no son comparables)
```

Todo lo demás del sistema (MCP, Claude Code, herramientas estructuradas) **no toca embeddings**.

---

## 7. Registro del servidor MCP en Claude Code

Claude Code descubre servidores MCP desde su configuración (`.mcp.json` a nivel proyecto o la
config de usuario). El servidor se lanza como subproceso (stdio). Esquema conceptual:

```jsonc
// .mcp.json (a nivel del proyecto o usuario) — VERIFICAR formato exacto en la doc de Claude Code
{
  "mcpServers": {
    "rag-scraper": {
      "command": "<python del entorno del MCP>",
      "args": ["<ruta>/rag_mcp_server.py"],
      "env": { "RAG_BASE_URL": "http://localhost:8001", "RAG_PROJECT_ID": "5" }
    }
  }
}
```

- **No requiere keys externas:** Claude Code ya está autenticado; el RAG es local; el MCP solo
  habla con `localhost:8001`.
- Tras registrarlo, Claude Code tiene las herramientas de §5 disponibles como tools nativas.
- VERIFICAR en la doc de Claude Code: ubicación exacta del `.mcp.json`, scopes (proyecto vs
  usuario), y cómo aprobar/activar el servidor.

---

## 8. Flujos de uso

### 8.1 Lectura (antes de una tarea) — recuperación granular
1. Claude decide que necesita contexto → `rag_search("…")` (o `get_*`/`list_*` si sabe el nombre).
2. Recibe top_k candidatos.
3. **Verifica contra el código/BD reales** (abre el archivo, corre un SELECT read-only).
4. Trabaja con ese contexto acotado.

### 8.2 Escritura / sync (después de un cambio) — la mitad que no hay que olvidar
1. Tras modificar código/doc/BD, Claude llama `rag_upsert_*` con la entidad afectada.
2. El RAG re-embebe esa entidad (momento de escritura, §6).
3. El índice queda sincronizado. **Entidad desincronizada = índice que miente.**

### 8.3 Indexado inicial (poblar el RAG) — una vez
- Cargar de forma INCREMENTAL: módulos (milestones/scripts), funciones clave, pantallas
  (pestañas del panel), documentos (`documentacion/*.md`, esquema de BD), requirements (R{n}).
- Cada carga dispara su embedding local. Verificar `embedding_ready` antes de confiar en `search`.

---

## 9. Reglas / no-negociables

- **Verificar antes de actuar:** el RAG son los planos; la realidad es código + `sports_db`.
  Nunca confiar a ciegas en lo recuperado (el top_k puede omitir o devolver algo viejo).
- **Reglas de seguridad SIEMPRE en el prompt del agente, nunca dependientes del retrieval**
  (no DELETE en `sports_db`, reglas del driver, dos venvs). Si una regla crítica solo viviera en
  el RAG y el top_k la omite, sería peligroso.
- **BD `sports_db`:** PROHIBIDO DELETE/DROP/TRUNCATE (regla del proyecto). El MCP no escribe en
  sports_db; solo lee/escribe en el RAG.
- **Requirements nuevos:** seguir el workflow obligatorio de `rag_inicio.md` (borrador →
  aprobación → migración); no escribir directo.
- **`/api/search/` sí, `/api/ask/` no** para el agente.

---

## 10. Pendientes / decisiones abiertas (a resolver juntos)

1. **Modelo de embeddings local:** ¿`bge-small` (384, liviano) / `bge-base` (768) /
   `multilingual-e5-base` (768, mejor para nombres ES/EN) / `nomic-embed-text` vía Ollama?
   → define dimensión de pgvector.
2. **Dónde corre el embedder:** ¿proceso embebido en el RAG (sentence-transformers en el venv del
   RAG) o servicio aparte (Ollama)? Impacto en RAM.
3. **Migración de pgvector:** confirmar dimensión actual de la columna y si hay vectores OpenAI
   que re-embeber; plan de migración (nueva columna vs alterar).
4. **Ubicación del servidor MCP:** `~/work/rag_system/mcp/` vs un repo/carpeta propia.
5. **Lenguaje del MCP:** Python (mismo venv que el RAG, requests a `:8001`) — probable.
6. **Set de herramientas v1:** ¿arrancamos con `rag_search` + `get_*`/`list_*` (lectura) y
   sumamos `upsert_*` (sync) en una v2?

---

## 11. Pasos de implementación (incremental, propuesto)

1. **RAG local-first:** elegir modelo (§10.1), cambiar backend de embeddings OpenAI→local en
   rag_system, ajustar dimensión pgvector, re-embeber lo cargado. Verificar `/api/search/`
   responde con `embedding_ready=true`.
2. **Servidor MCP v1 (solo lectura):** `rag_search`, `rag_get_function`, `rag_list_modules`,
   `rag_get_document`, `rag_list_requirements`. Probar con curl directo al RAG primero.
3. **Registrar en Claude Code** (`.mcp.json`) y probar una recuperación real end-to-end.
4. **Indexado inicial** incremental del proyecto (§8.3).
5. **Servidor MCP v2 (sync):** `upsert_*` + disciplina de escritura (§8.2).
6. **Actualizar el spec del agente #8** (`agents/new_agents/08_rag_knowledge.md`) para que use
   estas herramientas MCP en vez de asumir embeddings de OpenAI.

---

## Referencias
- `~/work/rag_system/rag_inicio.md` — API y workflow obligatorio del RAG.
- `agents/new_agents/08_rag_knowledge.md` — agente RAG (a actualizar en el paso 11.6).
- `documentacion/INDICE.md` — entrada del sistema de documentación (fuente de verdad).
