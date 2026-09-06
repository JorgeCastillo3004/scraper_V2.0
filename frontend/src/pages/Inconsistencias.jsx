import { useState, useEffect, useCallback, useRef } from 'react'
import {
  getInconsistencias,
  getDriverStatus, startDriver, stopDriver, getDriverHeadless, setDriverHeadless,
  getConfig, updateConfig, getFixScheduler, runFixSchedulerNow,
  getLiveMissing, setLiveMissingStatus, getSports,
} from '../api/client'
import useProcess   from '../hooks/useProcess'
import useWebSocket from '../hooks/useWebSocket'
import Terminal     from '../components/Terminal'
import DriverBar    from '../components/DriverBar'
import DbHistoryPanel from '../components/DbHistoryPanel'

// Tarjetas y a qué flujo de corrección mapea cada una.
const PENDING_KEY = 'score_minus_one'          // → update_pending_matches (pendientes -1)
const NOSTATS_KEY = 'no_statistics'            // → update_pending_matches --solo-sin-stats
const FIXNULL_KEYS = ['fk_roto_team', 'detail_no_score']  // → fix_null_team_ids
// Tarjetas con tabla de ligas seleccionable.
const SELECTABLE_KEYS = [PENDING_KEY, NOSTATS_KEY, ...FIXNULL_KEYS]

const SEVERITY_STYLE = {
  high:   'border-red-500/60    bg-red-500/10    text-red-300',
  medium: 'border-amber-500/60  bg-amber-500/10  text-amber-300',
  low:    'border-emerald-500/60 bg-emerald-500/10 text-emerald-300',
}

const SEVERITY_DOT = {
  high:   'bg-red-400',
  medium: 'bg-amber-400',
  low:    'bg-emerald-400',
}

function CardKPI({ item, active, onClick }) {
  const style = SEVERITY_STYLE[item.severity] || SEVERITY_STYLE.medium
  return (
    <button
      onClick={onClick}
      className={`text-left rounded border p-4 transition-all ${
        active ? 'ring-2 ring-blue-400/60' : 'hover:scale-[1.02]'
      } ${style}`}
    >
      <div className="flex items-center gap-2 mb-1">
        <span className={`inline-block w-2 h-2 rounded-full ${SEVERITY_DOT[item.severity]}`} />
        <span className="text-[10px] uppercase tracking-wider opacity-70">{item.severity}</span>
      </div>
      <div className="text-3xl font-bold">{item.count.toLocaleString()}</div>
      <div className="text-xs mt-1 opacity-90">{item.label}</div>
    </button>
  )
}

function ByLeagueTable({ rows, selectable, selectedIds, onToggle, onToggleAll }) {
  if (!rows || rows.length === 0) {
    return <p className="text-xs text-gray-500 italic">Sin desglose disponible.</p>
  }
  // Checkbox maestro: solo cuentan las ligas mapeables (las demás van deshabilitadas).
  const mappableRows = rows.filter(r => r.mappable)
  const allChecked  = mappableRows.length > 0 && mappableRows.every(r => selectedIds?.includes(r.league_id))
  const someChecked = mappableRows.some(r => selectedIds?.includes(r.league_id))
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-xs text-gray-400 border-b border-gray-800">
          {selectable && (
            <th className="w-8 py-2">
              <input
                type="checkbox"
                ref={el => { if (el) el.indeterminate = someChecked && !allChecked }}
                checked={allChecked}
                disabled={mappableRows.length === 0}
                onChange={onToggleAll}
                title="Seleccionar / quitar todas las ligas con problemas (mapeables)"
              />
            </th>
          )}
          <th className="text-left  py-2 font-normal">Deporte</th>
          <th className="text-left  py-2 font-normal">País / Confederación</th>
          <th className="text-left  py-2 font-normal">Liga</th>
          <th className="text-right py-2 font-normal">Cantidad</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => {
          const checked = selectedIds?.includes(r.league_id)
          return (
            <tr key={i} className="border-b border-gray-900 hover:bg-gray-900/40">
              {selectable && (
                <td className="py-1.5">
                  <input
                    type="checkbox"
                    checked={!!checked}
                    disabled={!r.mappable}
                    onChange={() => onToggle(r.league_id)}
                    title={r.mappable
                      ? 'Seleccionar para corregir'
                      : 'No mapeable: la liga no está en leagues_info o su league_id no coincide'}
                  />
                </td>
              )}
              <td className="py-1.5 text-gray-300">{r.sport ?? '—'}</td>
              <td className="py-1.5 text-gray-400">{r.country ?? '—'}</td>
              <td className="py-1.5 text-gray-300">
                {r.league}
                {selectable && !r.mappable && (
                  <span className="ml-2 text-[10px] text-amber-400/80">no mapeable</span>
                )}
              </td>
              <td className="py-1.5 text-right font-mono text-blue-300">{r.count}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

// ── Panel de actualización (completar partidos) reutilizable ──────────────────
function UpdatePanel({ title, subtitle, driver, proc, lines, clear,
                       selectedCount, mappableCount, apply, setApply, extras, onRun }) {
  const canRun = selectedCount > 0 && driver?.alive && !proc.isRunning
  return (
    <div className="bg-gray-900 rounded p-4 border border-gray-800 flex flex-col gap-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h3 className="text-sm font-medium text-gray-200">
          {title} — {apply
            ? <span className="text-red-300">escribe en la BD</span>
            : <span className="text-amber-300">dry-run (no escribe)</span>}
        </h3>
        <span className="text-xs text-gray-500">
          {selectedCount} liga(s) seleccionada(s) · {mappableCount} mapeable(s)
        </span>
      </div>

      {subtitle && <p className="text-xs text-gray-500">{subtitle}</p>}

      {!driver?.alive && (
        <p className="text-xs text-amber-400 bg-amber-950/30 border border-amber-800 rounded px-3 py-2">
          Iniciá el driver de corrección (arriba) antes de lanzar. La extracción lo reusa.
        </p>
      )}

      {extras}

      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={apply} onChange={e => setApply(e.target.checked)} />
        <span className={apply ? 'text-red-300 font-medium' : ''}>
          Escribir en la base de datos {apply
            ? '⚠ (NO es dry-run: se escribirán los cambios)'
            : <span className="text-gray-500">(desmarcado = dry-run, solo muestra)</span>}
        </span>
      </label>

      <div className="flex items-center gap-2 flex-wrap">
        {!proc.isRunning ? (
          <button
            onClick={onRun}
            disabled={proc.loading || !canRun}
            className={`px-4 py-2 rounded text-sm font-semibold text-white disabled:opacity-40 disabled:cursor-not-allowed ${
              apply ? 'bg-red-700 hover:bg-red-600' : 'bg-green-600 hover:bg-green-500'
            }`}
          >
            {apply ? '▶ Ejecutar (ESCRIBE en BD)' : '▶ Simular (dry-run)'}
          </button>
        ) : (
          <button
            onClick={proc.stop}
            disabled={proc.loading}
            className="px-4 py-2 bg-red-700 hover:bg-red-600 disabled:opacity-50 rounded text-sm font-semibold text-white"
          >
            ■ Detener
          </button>
        )}
        <span className="text-xs text-gray-500">
          Estado: {proc.status?.status ?? 'stopped'}
          {proc.status?.pid && ` · PID ${proc.status.pid}`}
        </span>
      </div>

      {proc.error && (
        <p className="text-red-400 text-xs bg-red-950/30 border border-red-800 rounded px-3 py-2">
          {proc.error}
        </p>
      )}

      <Terminal lines={lines} onClear={clear} />
    </div>
  )
}

// ── Ligas con partidos inexistentes detectadas por el LIVE ────────────────────
const LM_STATUS_STYLE = {
  pending:  'bg-amber-500/15 text-amber-300 border-amber-500/40',
  resolved: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
  ignored:  'bg-gray-600/20 text-gray-400 border-gray-600/40',
}

function LiveMissingPanel() {
  const [data, setData]     = useState(null)
  const [loading, setLoad]  = useState(false)
  const [error, setError]   = useState(null)
  const [busyKey, setBusy]  = useState(null)
  const [extractMsg, setExtractMsg] = useState(null)
  const [extractApply, setExtractApply]       = useState(true)   // escritura en BD habilitada por defecto
  const [extractOwnDriver, setExtractOwnDriver] = useState(false) // por defecto: mismo driver
  const [allSports, setAllSports]   = useState([])   // 9 deportes que monitorea Live (getSports)
  const [sweepSel, setSweepSel]     = useState([])   // deportes marcados para el barrido
  // Auto-status: liga(s) en extracción + si fue apply, para marcar "resuelta" al terminar.
  const [extractingKeys, setExtractingKeys]   = useState([])     // keys de live_missing en curso
  const [extractingApply, setExtractingApply] = useState(false)
  const prevRunning = useRef(false)
  const extractProc = useProcess('extract_fixtures')   // crear_fixtures_ligas.py por liga
  const { lines: extractLines, clear: extractClear } = useWebSocket('extract_fixtures')

  const load = useCallback(() => {
    setLoad(true); setError(null)
    getLiveMissing()
      .then(({ data }) => setData(data))
      .catch(e => setError(e.message || 'Error al cargar'))
      .finally(() => setLoad(false))
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 30_000)
    return () => clearInterval(t)
  }, [load])

  // Deportes que monitorea Live (para el barrido multi-deporte). Default: todos.
  useEffect(() => {
    getSports().then(({ data }) => { setAllSports(data); setSweepSel(data) }).catch(() => {})
  }, [])

  // Auto-status: cuando una extracción APPLY termina (running -> stopped), marca
  // automáticamente como "resuelta" la(s) liga(s) que se estaban extrayendo.
  useEffect(() => {
    const was = prevRunning.current
    prevRunning.current = extractProc.isRunning
    if (was && !extractProc.isRunning && extractingApply && extractingKeys.length) {
      Promise.allSettled(extractingKeys.map(k => setLiveMissingStatus(k, 'resolved')))
        .finally(() => { setExtractingKeys([]); load() })
    }
  }, [extractProc.isRunning, extractingApply, extractingKeys, load])

  const changeStatus = async (key, status) => {
    setBusy(key)
    try { await setLiveMissingStatus(key, status); load() }
    catch (e) { setError(e.message || 'Error al actualizar') }
    finally { setBusy(null) }
  }

  // Extrae una liga REGISTRADA con crear_fixtures_ligas.py: navega fixtures,
  // expande "mostrar más", recorre cada match y crea teams/match/score faltantes.
  const extractLeague = async (r) => {
    // Por ahora la extracción asume liga existente. Si no existe → mensaje.
    if (!r.in_leagues_info || !r.sport_key || !r.league_key) {
      setExtractMsg({ ok: false, text: `La liga "${r.league}" (${r.country}) no existe en la base de datos. `
        + 'Más adelante se creará con el script de creación de una liga en particular.' })
      return
    }
    if (extractProc.isRunning) {
      setExtractMsg({ ok: false, text: 'Ya hay una extracción en curso. Esperá a que termine.' })
      return
    }
    const driverTxt = extractOwnDriver ? 'driver PROPIO (nuevo)' : 'el mismo driver de corrección'
    const writeTxt  = extractApply ? 'ESCRIBE en la BD (apply)' : 'dry-run (no escribe)'
    if (!window.confirm(`Extraer fixtures de ${r.sport_key} / ${r.league_key}?\n`
      + `· Driver: ${driverTxt}\n· Modo: ${writeTxt}\n`
      + 'Navega la sección fixtures, expande todos los partidos y crea los faltantes.')) return
    setExtractMsg(null)
    setExtractingKeys([r.key]); setExtractingApply(extractApply)   // auto-status al terminar
    try {
      await extractProc.start({
        leagues: [{ sport: r.sport_key, key: r.league_key }],
        apply: extractApply,
        own_driver: extractOwnDriver,
      })
      setExtractMsg({ ok: true, text: `Extracción lanzada para ${r.league} (${writeTxt}, ${driverTxt}). `
        + 'Seguí el progreso abajo. Al terminar y aparecer los partidos, marcá la liga como Resuelta.' })
    } catch (e) {
      setExtractMsg({ ok: false, text: e.message || 'No se pudo lanzar la extracción' })
    }
  }

  // Crea los partidos de HOY desde la página summary de la liga (jugados
  // COMPLETED+score, live LIVE+score, próximos SCHEDULED). Es lo que faltaba para
  // los detectados por el Live. Reusa el mismo proceso/checkboxes que "Extraer".
  const extractLeagueToday = async (r) => {
    if (!r.in_leagues_info || !r.sport_key || !r.league_key) {
      setExtractMsg({ ok: false, text: `La liga "${r.league}" (${r.country}) no existe en la base de datos.` })
      return
    }
    if (extractProc.isRunning) {
      setExtractMsg({ ok: false, text: 'Ya hay una extracción en curso. Esperá a que termine.' })
      return
    }
    const driverTxt = extractOwnDriver ? 'driver PROPIO (nuevo)' : 'el mismo driver de corrección'
    const writeTxt  = extractApply ? 'ESCRIBE en la BD (apply)' : 'dry-run (no escribe)'
    if (!window.confirm(`Crear los partidos de HOY de ${r.sport_key} / ${r.league_key}?\n`
      + `· Driver: ${driverTxt}\n· Modo: ${writeTxt}\n`
      + 'Lee la página summary y crea los partidos de hoy con su status+score reales '
      + '(jugados COMPLETED, en vivo LIVE, próximos SCHEDULED).')) return
    setExtractMsg(null)
    setExtractingKeys([r.key]); setExtractingApply(extractApply)   // auto-status al terminar
    try {
      await extractProc.start({
        leagues: [{ sport: r.sport_key, key: r.league_key }],
        apply: extractApply,
        own_driver: extractOwnDriver,
        today: true,
      })
      setExtractMsg({ ok: true, text: `Creación de partidos de HOY lanzada para ${r.league} (${writeTxt}). `
        + 'Seguí el progreso abajo. Al terminar y aparecer los partidos, marcá la liga como Resuelta.' })
    } catch (e) {
      setExtractMsg({ ok: false, text: e.message || 'No se pudo lanzar' })
    }
  }

  // Barrido a nivel DEPORTE: entra al link del deporte, detecta TODAS las ligas
  // pineadas con partidos de hoy faltantes y los crea (cubre lo que el Live no vio).
  const sweepPinned = async (sports) => {
    if (!sports || sports.length === 0) {
      setExtractMsg({ ok: false, text: 'Marcá al menos un deporte para barrer.' }); return
    }
    if (extractProc.isRunning) {
      setExtractMsg({ ok: false, text: 'Ya hay una extracción en curso. Esperá a que termine.' }); return
    }
    const writeTxt  = extractApply ? 'ESCRIBE en la BD (apply)' : 'dry-run (no escribe)'
    const driverTxt = extractOwnDriver ? 'driver PROPIO (nuevo)' : 'el mismo driver de corrección'
    if (!window.confirm(`Verificar y crear los faltantes de HOY de las pineadas de: ${sports.join(', ')}?\n`
      + `· Driver: ${driverTxt}\n· Modo: ${writeTxt}\n`
      + 'Entra al link de cada deporte, detecta las pineadas con partidos de hoy faltantes en la BD '
      + 'y los crea desde la summary (status+score reales).')) return
    setExtractMsg(null)
    // auto-status: al terminar (apply) marca resueltas las pending de esos deportes.
    setExtractingKeys((data?.items ?? [])
      .filter(i => i.status === 'pending' && sports.includes(i.sport)).map(i => i.key))
    setExtractingApply(extractApply)
    try {
      await extractProc.start({
        sports, from_pin: true, today: true,
        apply: extractApply, own_driver: extractOwnDriver,
      })
      setExtractMsg({ ok: true, text: `Barrido de pineadas lanzado para ${sports.join(', ')} (${writeTxt}). `
        + 'Detecta y crea TODOS los faltantes de hoy. Seguí el progreso abajo.' })
    } catch (e) {
      setExtractMsg({ ok: false, text: e.message || 'No se pudo lanzar el barrido' })
    }
  }

  const fmt = (iso) => iso ? new Date(iso).toLocaleString() : '—'
  const items  = data?.items ?? []
  const counts = data?.counts ?? {}
  const toggleSweepSport = (s) =>
    setSweepSel(prev => prev.includes(s) ? prev.filter(x => x !== s) : [...prev, s])

  return (
    <div className="bg-gray-900 rounded p-4 border border-gray-800 flex flex-col gap-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h3 className="text-sm font-medium text-gray-200">
          Ligas con partidos inexistentes detectadas por el Live
        </h3>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-500">
            {data?.total ?? 0} ligas · {counts.pending ?? 0} pendientes ·{' '}
            {counts.in_leagues_info ?? 0} registradas · {counts.new ?? 0} nuevas
          </span>
          <button onClick={load} disabled={loading}
            className="px-3 py-1.5 text-xs rounded bg-blue-600/30 border border-blue-500 text-blue-300 hover:bg-blue-600/40 disabled:opacity-50">
            {loading ? 'Cargando…' : 'Refrescar'}
          </button>
        </div>
      </div>

      <p className="text-xs text-gray-500">
        El live registra acá cada liga cuyos partidos vio en vivo pero no estaban en
        la BD. <b>Registrada</b> = ya existe en <code>leagues_info</code> (se puede
        extraer con el botón <b>Extraer</b>). <b>Nueva</b> = liga desconocida, requiere alta manual.
      </p>

      {/* Opciones de extracción (aplican al botón "Extraer" de cada liga registrada) */}
      <div className="flex items-center gap-5 flex-wrap text-sm bg-gray-950/40 border border-gray-800 rounded px-3 py-2">
        <span className="text-xs text-gray-500">Extracción (crear_fixtures_ligas):</span>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={extractOwnDriver}
                 onChange={e => setExtractOwnDriver(e.target.checked)} />
          <span>Lanzar driver propio
            <span className="text-gray-500"> (por defecto usa el mismo driver de corrección)</span>
          </span>
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={extractApply}
                 onChange={e => setExtractApply(e.target.checked)} />
          <span className={extractApply ? 'text-red-300 font-medium' : ''}>
            Escribir en BD {extractApply ? '⚠ (apply)' : <span className="text-gray-500">(dry-run)</span>}
          </span>
        </label>
        <span className="text-xs text-gray-500">
          {extractProc.isRunning ? '● extrayendo…' : 'inactivo'}
        </span>
      </div>

      {/* Barrido a nivel DEPORTE: cubre TODOS los faltantes de las pineadas (lo que
          el Live indica + lo que no llegó a ver). Usa los checkboxes de arriba. */}
      <div className="flex items-center gap-3 flex-wrap text-sm bg-purple-950/20 border border-purple-900/50 rounded px-3 py-2">
        <span className="text-xs text-purple-300/80">Verificar pineadas — deportes:</span>
        <div className="flex gap-1.5 flex-wrap">
          {allSports.map(s => (
            <button key={s} onClick={() => toggleSweepSport(s)}
              className={`px-2 py-0.5 rounded text-[11px] border ${
                sweepSel.includes(s)
                  ? 'bg-purple-600/40 border-purple-500 text-purple-200'
                  : 'border-gray-700 text-gray-500 hover:border-gray-500'}`}>
              {s}
            </button>
          ))}
        </div>
        <button onClick={() => sweepPinned(sweepSel)}
                disabled={extractProc.isRunning || sweepSel.length === 0}
                title="Por cada deporte marcado: entra a su link, detecta las pineadas con partidos de hoy faltantes y los crea desde la summary"
                className="text-[11px] px-2 py-1 rounded bg-purple-700/50 border border-purple-600 text-purple-200 hover:bg-purple-700/70 disabled:opacity-40">
          Verificar y crear faltantes de pineadas
        </button>
        <span className="text-[11px] text-gray-500">cubre todo lo faltante de hoy · usa los checkboxes de arriba (dry-run/apply, driver)</span>
      </div>

      {error && (
        <p className="text-red-400 text-xs bg-red-950/30 border border-red-800 rounded px-3 py-2">{error}</p>
      )}

      {extractMsg && (
        <p className={`text-xs rounded px-3 py-2 border ${
          extractMsg.ok ? 'text-emerald-300 bg-emerald-950/30 border-emerald-800'
                        : 'text-red-400 bg-red-950/30 border-red-800'}`}>
          {extractMsg.text}
        </p>
      )}

      {items.length === 0 ? (
        <p className="text-xs text-gray-500 italic">
          Sin ligas detectadas por el live todavía. {data?.updated_at && `(Actualizado: ${fmt(data.updated_at)})`}
        </p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-gray-400 border-b border-gray-800">
              <th className="text-left  py-2 font-normal">Deporte</th>
              <th className="text-left  py-2 font-normal">País</th>
              <th className="text-left  py-2 font-normal">Liga</th>
              <th className="text-right py-2 font-normal">Veces</th>
              <th className="text-left  py-2 font-normal">Últ. detección</th>
              <th className="text-left  py-2 font-normal">Registro</th>
              <th className="text-left  py-2 font-normal">Estado</th>
              <th className="text-right py-2 font-normal">Acción</th>
            </tr>
          </thead>
          <tbody>
            {items.map((r) => (
              <tr key={r.key} className="border-b border-gray-900 hover:bg-gray-900/40 align-top">
                <td className="py-1.5 text-gray-300">{r.sport}</td>
                <td className="py-1.5 text-gray-400">{r.country || '—'}</td>
                <td className="py-1.5 text-gray-300">
                  {r.league || '—'}
                  {r.sample_matches?.length > 0 && (
                    <span className="block text-[10px] text-gray-600 truncate max-w-[260px]"
                          title={r.sample_matches.join(', ')}>
                      {r.sample_matches.slice(0, 3).join(' · ').replaceAll('~', ' vs ')}
                    </span>
                  )}
                </td>
                <td className="py-1.5 text-right font-mono text-blue-300">{r.count}</td>
                <td className="py-1.5 text-gray-500 text-xs">{fmt(r.last_seen)}</td>
                <td className="py-1.5">
                  {r.in_leagues_info
                    ? <span className="text-[10px] text-emerald-400" title={`${r.sport_key}/${r.league_key}`}>✓ registrada</span>
                    : <span className="text-[10px] text-amber-400">nueva</span>}
                </td>
                <td className="py-1.5">
                  {extractingKeys.includes(r.key) && extractProc.isRunning ? (
                    <span className="text-[10px] px-2 py-0.5 rounded border bg-blue-500/15 text-blue-300 border-blue-500/40 animate-pulse">
                      extrayendo…
                    </span>
                  ) : (
                    <span className={`text-[10px] px-2 py-0.5 rounded border ${LM_STATUS_STYLE[r.status] || LM_STATUS_STYLE.pending}`}>
                      {r.status}
                    </span>
                  )}
                </td>
                <td className="py-1.5 text-right whitespace-nowrap">
                  <button onClick={() => extractLeague(r)} disabled={extractProc.isRunning}
                    title={r.in_leagues_info
                      ? 'Extraer fixtures de esta liga (crea teams/match/score faltantes)'
                      : 'La liga no existe en la base de datos (mostrará un aviso)'}
                    className={`text-[11px] px-2 py-1 rounded border mr-1 disabled:opacity-40 ${
                      r.in_leagues_info
                        ? 'bg-blue-700/50 border-blue-600 text-blue-200 hover:bg-blue-700/70'
                        : 'bg-gray-800/50 border-gray-700 text-gray-400 hover:bg-gray-800'}`}>
                    Extraer
                  </button>
                  <button onClick={() => extractLeagueToday(r)} disabled={extractProc.isRunning || !r.in_leagues_info}
                    title="Crear los partidos de HOY de esta liga desde la summary (status+score reales: COMPLETED/LIVE/SCHEDULED)"
                    className={`text-[11px] px-2 py-1 rounded border mr-1 disabled:opacity-40 ${
                      r.in_leagues_info
                        ? 'bg-purple-700/50 border-purple-600 text-purple-200 hover:bg-purple-700/70'
                        : 'bg-gray-800/50 border-gray-700 text-gray-500'}`}>
                    Crear HOY
                  </button>
                  {r.status !== 'resolved' && (
                    <button onClick={() => changeStatus(r.key, 'resolved')} disabled={busyKey === r.key}
                      className="text-[11px] px-2 py-1 rounded bg-emerald-700/40 border border-emerald-700 text-emerald-300 hover:bg-emerald-700/60 disabled:opacity-40 mr-1">
                      Resuelta
                    </button>
                  )}
                  {r.status !== 'ignored' && (
                    <button onClick={() => changeStatus(r.key, 'ignored')} disabled={busyKey === r.key}
                      className="text-[11px] px-2 py-1 rounded bg-gray-700/40 border border-gray-700 text-gray-300 hover:bg-gray-700/60 disabled:opacity-40 mr-1">
                      Ignorar
                    </button>
                  )}
                  {r.status !== 'pending' && (
                    <button onClick={() => changeStatus(r.key, 'pending')} disabled={busyKey === r.key}
                      className="text-[11px] px-2 py-1 rounded bg-amber-700/40 border border-amber-700 text-amber-300 hover:bg-amber-700/60 disabled:opacity-40">
                      Reabrir
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Recuadro de progreso: TODAS las impresiones de crear_fixtures_ligas.py
          (creación de equipos, matches, etc.) en vivo vía WebSocket. */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-gray-400 font-medium">
            Progreso de la extracción (crear_fixtures_ligas)
          </span>
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500">
              {extractProc.status?.status ?? 'stopped'}
              {extractProc.status?.pid && ` · PID ${extractProc.status.pid}`}
            </span>
            {extractProc.isRunning && (
              <button onClick={extractProc.stop} disabled={extractProc.loading}
                className="px-3 py-1 text-xs rounded bg-red-700 hover:bg-red-600 text-white disabled:opacity-50">
                ■ Detener
              </button>
            )}
          </div>
        </div>
        <Terminal lines={extractLines} onClear={extractClear} />
      </div>
    </div>
  )
}

// ── Programación diaria de la corrección de team_id inexistente ───────────────
function FixSchedulerPanel() {
  const [enabled, setEnabled] = useState(false)
  const [atHour, setAtHour]   = useState('04:00')
  const [apply, setApply]     = useState(true)   // escritura en BD habilitada por defecto
  const [sched, setSched]     = useState(null)
  const [saving, setSaving]   = useState(false)
  const [running, setRunning] = useState(false)
  const [msg, setMsg]         = useState(null)

  const refreshSched = useCallback(() => {
    getFixScheduler().then(({ data }) => setSched(data)).catch(() => {})
  }, [])

  useEffect(() => {
    getConfig().then(({ data }) => {
      const c = data?.FIX_TEAM_IDS || {}
      if (typeof c.ENABLED === 'boolean') setEnabled(c.ENABLED)
      if (c.AT_HOUR) setAtHour(c.AT_HOUR)
      if (typeof c.APPLY === 'boolean') setApply(c.APPLY)
    }).catch(() => {})
    refreshSched()
    const t = setInterval(refreshSched, 15_000)
    return () => clearInterval(t)
  }, [refreshSched])

  const save = async () => {
    setSaving(true); setMsg(null)
    try {
      await updateConfig({ FIX_TEAM_IDS: { ENABLED: enabled, AT_HOUR: atHour, APPLY: apply, EXCLUDE: sched?.exclude || [] } })
      setMsg({ ok: true, text: 'Programación guardada.' })
      refreshSched()
    } catch (e) {
      setMsg({ ok: false, text: e.message || 'Error al guardar' })
    } finally { setSaving(false) }
  }

  const runNow = async () => {
    if (!window.confirm(apply
      ? 'Vas a disparar la corrección AHORA y ESCRIBE en la BD (apply=true). ¿Continuar?'
      : 'Vas a disparar la corrección AHORA en modo dry-run (no escribe). ¿Continuar?')) return
    setRunning(true); setMsg(null)
    try {
      const { data } = await runFixSchedulerNow()
      setMsg(data?.ok
        ? { ok: true, text: data.note || 'Corrección disparada.' }
        : { ok: false, text: data?.error || 'No se pudo disparar.' })
      refreshSched()
    } catch (e) {
      setMsg({ ok: false, text: e.message || 'Error al disparar' })
    } finally { setRunning(false) }
  }

  const fmt = (iso) => iso ? new Date(iso).toLocaleString() : '—'

  return (
    <div className="bg-gray-900 rounded p-4 border border-gray-800 flex flex-col gap-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h3 className="text-sm font-medium text-gray-200">
          Programación diaria — corregir teams inexistentes (modo dinámico)
        </h3>
        <span className="text-xs text-gray-500">
          {sched?.running ? '● corriendo ahora' : 'inactivo'}
          {sched?.driver_alive ? ' · driver vivo' : ' · driver detenido'}
        </span>
      </div>

      <p className="text-xs text-gray-500">
        A la hora indicada consulta el resumen y ataca <b>todas</b> las ligas mapeables
        con <code>team_id</code> inexistente. Usa el driver de corrección (lo levanta
        headless si hace falta); nunca toca el driver de live.
      </p>

      <div className="flex items-center gap-4 flex-wrap">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} />
          <span>Activar disparo diario</span>
        </label>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-gray-400">Hora</span>
          <input type="time" value={atHour} onChange={e => setAtHour(e.target.value)}
                 className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm" />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={apply} onChange={e => setApply(e.target.checked)} />
          <span className={apply ? 'text-red-300 font-medium' : ''}>
            Escribir en BD {apply ? '⚠ (apply)' : <span className="text-gray-500">(dry-run)</span>}
          </span>
        </label>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
        <div><span className="text-gray-500">Última corrida</span><br/><span className="text-gray-300">{fmt(sched?.last_run)}</span></div>
        <div><span className="text-gray-500">Próxima</span><br/><span className="text-gray-300">{fmt(sched?.next_run)}</span></div>
        <div><span className="text-gray-500">Ligas última vez</span><br/><span className="text-gray-300">{sched?.last_leagues ?? '—'}</span></div>
        <div><span className="text-gray-500">Último error</span><br/><span className={sched?.last_error ? 'text-red-400' : 'text-gray-300'}>{sched?.last_error || '—'}</span></div>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <button onClick={save} disabled={saving}
          className="px-4 py-2 rounded text-sm font-semibold text-white bg-blue-600 hover:bg-blue-500 disabled:opacity-40">
          {saving ? 'Guardando…' : 'Guardar programación'}
        </button>
        <button onClick={runNow} disabled={running || sched?.running}
          className={`px-4 py-2 rounded text-sm font-semibold text-white disabled:opacity-40 ${
            apply ? 'bg-red-700 hover:bg-red-600' : 'bg-green-600 hover:bg-green-500'}`}>
          {running ? 'Disparando…' : (apply ? '▶ Ejecutar ahora (ESCRIBE)' : '▶ Simular ahora (dry-run)')}
        </button>
      </div>

      {msg && (
        <p className={`text-xs rounded px-3 py-2 border ${
          msg.ok ? 'text-emerald-300 bg-emerald-950/30 border-emerald-800'
                 : 'text-red-400 bg-red-950/30 border-red-800'}`}>
          {msg.text}
        </p>
      )}
    </div>
  )
}

export default function Inconsistencias() {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const [selected, setSelected] = useState(null)
  const [selectedIds, setSelectedIds] = useState([])

  // Opciones de actualización
  const [extractStats, setExtractStats] = useState(true)   // estadísticas (extra opcional)
  const [applyWrite, setApplyWrite]     = useState(true)   // escritura en BD habilitada por defecto

  // Driver
  const [driver, setDriver] = useState(null)
  const [driverBusy, setDriverBusy] = useState(false)
  const [headlessPref, setHeadlessPref] = useState(false)  // preferencia headless (próximo inicio)

  // Procesos + logs en vivo (fix_null_team_ids y update_pending_matches)
  const fixProc = useProcess('fix_results')
  const updProc = useProcess('update_matches')
  const { lines: fixLines, clear: fixClear } = useWebSocket('fix_results')
  const { lines: updLines, clear: updClear } = useWebSocket('update_matches')

  // fresh=true (botón Refrescar) saltea el caché de 60 s del backend y consulta
  // la BD; el auto-refresh usa el caché para no martillar Postgres.
  const load = (fresh = false) => {
    setLoading(true)
    setError(null)
    getInconsistencias(fresh)
      .then(({ data }) => {
        setData(data)
        if (!selected && data.items?.length) setSelected(data.items[0].key)
      })
      .catch((e) => setError(e.message || 'Error al cargar'))
      .finally(() => setLoading(false))
  }

  const refreshDriver = useCallback(() => {
    getDriverStatus().then(({ data }) => setDriver(data)).catch(() => {})
    getDriverHeadless().then(({ data }) => setHeadlessPref(!!data.effective)).catch(() => {})
  }, [])

  const onToggleHeadless = async (val) => {
    setHeadlessPref(val)  // optimista
    try { await setDriverHeadless(val) } catch (_) {}
    finally { refreshDriver() }
  }

  useEffect(() => {
    load()
    refreshDriver()
    const id  = setInterval(() => load(false), 60_000)   // auto-refresh: usa caché
    const idd = setInterval(refreshDriver, 5_000)
    return () => { clearInterval(id); clearInterval(idd) }
  }, [])

  // Al cambiar de tarjeta, reseteamos selección de ligas y el flag de escritura.
  useEffect(() => { setSelectedIds([]); setApplyWrite(true) }, [selected])

  const onStartDriver = async () => {
    setDriverBusy(true)
    try { await startDriver() } catch (_) {}
    finally { setDriverBusy(false); refreshDriver() }
  }
  const onStopDriver = async () => {
    setDriverBusy(true)
    try { await stopDriver() } catch (_) {}
    finally { setDriverBusy(false); refreshDriver() }
  }

  const items = data?.items ?? []
  const byLeague = selected ? data?.by_league?.[selected] : null
  const selectedItem = items.find((it) => it.key === selected)
  const isSelectable = SELECTABLE_KEYS.includes(selected)

  const toggleId = (id) =>
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])

  const selectableRows = (byLeague || []).filter(r => r.mappable)

  // Seleccionar/quitar TODAS las ligas con problemas que sean mapeables.
  const toggleAll = () => {
    const ids = selectableRows.map(r => r.league_id)
    const allSel = ids.length > 0 && ids.every(id => selectedIds.includes(id))
    setSelectedIds(allSel ? [] : ids)
  }
  const selectedLeagues = (byLeague || [])
    .filter(r => r.mappable && selectedIds.includes(r.league_id))
    .map(r => ({ sport: r.sport_key, key: r.league_key }))

  const confirmIfApply = () =>
    !applyWrite || window.confirm('Vas a ESCRIBIR en la base de datos (no es dry-run). ¿Continuar?')

  // fix_null_team_ids (fk_roto_team / detail_no_score)
  const onRunFix = () => {
    if (!selectedLeagues.length || !driver?.alive || !confirmIfApply()) return
    fixClear()
    fixProc.start({ leagues: selectedLeagues, apply: applyWrite })
  }

  // update_pending_matches — pendientes con score -1
  const onRunPending = () => {
    if (!selectedLeagues.length || !driver?.alive || !confirmIfApply()) return
    updClear()
    updProc.start({
      leagues: selectedLeagues,
      mode: extractStats ? 'completo' : 'rapido',
      solo_sin_stats: false,
      apply: applyWrite,
    })
  }

  // update_pending_matches — backfill de estadísticas (ya con resultado)
  const onRunNostats = () => {
    if (!selectedLeagues.length || !driver?.alive || !confirmIfApply()) return
    updClear()
    updProc.start({
      leagues: selectedLeagues,
      mode: 'completo',
      solo_sin_stats: true,
      apply: applyWrite,
    })
  }

  return (
    <div className="flex flex-col gap-6 max-w-6xl">
      <div className="flex items-end justify-between">
        <div>
          <h2 className="text-lg font-semibold">Inconsistencias en la base de datos</h2>
          <p className="text-xs text-gray-500 mt-1">
            Diagnóstico de integridad. Click en una tarjeta para ver el desglose por liga;
            en las corregibles podés seleccionar ligas y lanzar la corrección desde acá.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {data?.timestamp && (
            <span className="text-xs text-gray-500">
              Actualizado: {new Date(data.timestamp).toLocaleString()}
            </span>
          )}
          <button
            onClick={() => load(true)}
            disabled={loading}
            className="px-3 py-1.5 text-xs rounded bg-blue-600/30 border border-blue-500 text-blue-300 hover:bg-blue-600/40 disabled:opacity-50"
          >
            {loading ? 'Cargando…' : 'Refrescar'}
          </button>
        </div>
      </div>

      <DriverBar driver={driver} busy={driverBusy} onStart={onStartDriver} onStop={onStopDriver}
                 label="Driver de corrección:"
                 headlessPref={headlessPref} onToggleHeadless={onToggleHeadless} />

      <FixSchedulerPanel />

      <LiveMissingPanel />

      {error && (
        <div className="rounded border border-red-500/60 bg-red-500/10 text-red-300 p-3 text-sm">
          {error}
        </div>
      )}

      {data?.error && (
        <div className="rounded border border-red-500/60 bg-red-500/10 text-red-300 p-3 text-sm">
          Error del servidor: {data.error}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
        {items.map((it) => (
          <CardKPI
            key={it.key}
            item={it}
            active={selected === it.key}
            onClick={() => setSelected(it.key)}
          />
        ))}
      </div>

      <div className="bg-gray-900 rounded p-4 border border-gray-800">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-gray-200">
            Desglose por liga
            {selectedItem && (
              <span className="text-gray-500 font-normal"> — {selectedItem.label}</span>
            )}
          </h3>
          <span className="text-[11px] text-gray-500">Top 15</span>
        </div>
        <ByLeagueTable
          rows={byLeague}
          selectable={isSelectable}
          selectedIds={selectedIds}
          onToggle={toggleId}
          onToggleAll={toggleAll}
        />
      </div>

      {/* Panel: completar partidos pendientes (score = -1) */}
      {selected === PENDING_KEY && (
        <UpdatePanel
          title="Actualizar resultados (score = -1)"
          subtitle="Obtiene el resultado real (score + detalles) de cada partido pasado con -1. Las estadísticas son un extra opcional."
          driver={driver} proc={updProc} lines={updLines} clear={updClear}
          selectedCount={selectedIds.length} mappableCount={selectableRows.length}
          apply={applyWrite} setApply={setApplyWrite}
          onRun={onRunPending}
          extras={
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={extractStats}
                     onChange={e => setExtractStats(e.target.checked)} />
              <span>Extraer estadísticas también
                <span className="text-gray-500"> (desmarcar = más rápido, solo score + detalles)</span>
              </span>
            </label>
          }
        />
      )}

      {/* Panel: backfill de estadísticas (ya con resultado) */}
      {selected === NOSTATS_KEY && (
        <UpdatePanel
          title="Completar estadísticas faltantes"
          subtitle="Solo partidos que YA tienen resultado (COMPLETED) y les faltan las estadísticas. No toca score ni status."
          driver={driver} proc={updProc} lines={updLines} clear={updClear}
          selectedCount={selectedIds.length} mappableCount={selectableRows.length}
          apply={applyWrite} setApply={setApplyWrite}
          onRun={onRunNostats}
          extras={null}
        />
      )}

      {/* Panel: corrección de teams inexistentes con fix_null_team_ids (FK rota / sin score_entity) */}
      {FIXNULL_KEYS.includes(selected) && (
        <UpdatePanel
          title="Corregir teams inexistentes (FK rota / sin score_entity)"
          subtitle="Navega FlashScore para crear los teams faltantes y reparar el score_entity de los partidos de las ligas seleccionadas. fix_null_team_ids reusa el driver vivo."
          driver={driver} proc={fixProc} lines={fixLines} clear={fixClear}
          selectedCount={selectedIds.length} mappableCount={selectableRows.length}
          apply={applyWrite} setApply={setApplyWrite}
          onRun={onRunFix}
          extras={null}
        />
      )}

      {/* Estado por liga (desde logs) + visor de db_history — al fondo */}
      <DbHistoryPanel />
    </div>
  )
}
