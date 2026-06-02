import { useState, useEffect, useCallback } from 'react'
import {
  getInconsistencias,
  getDriverStatus, startDriver, stopDriver,
} from '../api/client'
import useProcess   from '../hooks/useProcess'
import useWebSocket from '../hooks/useWebSocket'
import Terminal     from '../components/Terminal'

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

function ByLeagueTable({ rows, selectable, selectedIds, onToggle }) {
  if (!rows || rows.length === 0) {
    return <p className="text-xs text-gray-500 italic">Sin desglose disponible.</p>
  }
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-xs text-gray-400 border-b border-gray-800">
          {selectable && <th className="w-8 py-2"></th>}
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

// ── Barra de control del driver dedicado ──────────────────────────────────────
function DriverBar({ driver, busy, onStart, onStop }) {
  const alive = driver?.alive
  const launching = driver?.launcher_running && !driver?.session_ready
  return (
    <div className="flex items-center gap-3 flex-wrap bg-gray-900 rounded p-3 border border-gray-800">
      <span className="text-sm text-gray-300 font-medium">Driver de corrección:</span>
      <span className={`text-xs px-2 py-0.5 rounded-full border ${
        alive ? 'border-green-500/60 bg-green-500/10 text-green-300'
              : launching ? 'border-amber-500/60 bg-amber-500/10 text-amber-300'
                          : 'border-gray-600 bg-gray-800 text-gray-400'
      }`}>
        {alive ? 'activo' : launching ? 'iniciando…' : 'detenido'}
      </span>
      {driver?.pid && <span className="text-xs text-gray-500">PID {driver.pid}</span>}
      {typeof driver?.headless === 'boolean' && (
        <span className="text-xs text-gray-500">{driver.headless ? 'headless' : 'visible'}</span>
      )}
      <div className="flex-1" />
      <button
        onClick={onStart}
        disabled={busy || driver?.launcher_running}
        className="px-3 py-1.5 text-xs rounded bg-green-600/30 border border-green-500 text-green-300 hover:bg-green-600/40 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        ▶ Iniciar driver
      </button>
      <button
        onClick={onStop}
        disabled={busy || !driver?.launcher_running}
        className="px-3 py-1.5 text-xs rounded bg-red-700/30 border border-red-600 text-red-300 hover:bg-red-700/40 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        ■ Matar driver
      </button>
    </div>
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

export default function Inconsistencias() {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const [selected, setSelected] = useState(null)
  const [selectedIds, setSelectedIds] = useState([])

  // Opciones de actualización
  const [extractStats, setExtractStats] = useState(true)   // estadísticas (extra opcional)
  const [applyWrite, setApplyWrite]     = useState(false)  // dry-run por defecto

  // Driver
  const [driver, setDriver] = useState(null)
  const [driverBusy, setDriverBusy] = useState(false)

  // Procesos + logs en vivo (fix_null_team_ids y update_pending_matches)
  const fixProc = useProcess('fix_results')
  const updProc = useProcess('update_matches')
  const { lines: fixLines, clear: fixClear } = useWebSocket('fix_results')
  const { lines: updLines, clear: updClear } = useWebSocket('update_matches')

  const load = () => {
    setLoading(true)
    setError(null)
    getInconsistencias()
      .then(({ data }) => {
        setData(data)
        if (!selected && data.items?.length) setSelected(data.items[0].key)
      })
      .catch((e) => setError(e.message || 'Error al cargar'))
      .finally(() => setLoading(false))
  }

  const refreshDriver = useCallback(() => {
    getDriverStatus().then(({ data }) => setDriver(data)).catch(() => {})
  }, [])

  useEffect(() => {
    load()
    refreshDriver()
    const id  = setInterval(load, 60_000)
    const idd = setInterval(refreshDriver, 5_000)
    return () => { clearInterval(id); clearInterval(idd) }
  }, [])

  // Al cambiar de tarjeta, reseteamos selección de ligas y el flag de escritura.
  useEffect(() => { setSelectedIds([]); setApplyWrite(false) }, [selected])

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
  const selectedLeagues = (byLeague || [])
    .filter(r => r.mappable && selectedIds.includes(r.league_id))
    .map(r => ({ sport: r.sport_key, key: r.league_key }))

  const confirmIfApply = () =>
    !applyWrite || window.confirm('Vas a ESCRIBIR en la base de datos (no es dry-run). ¿Continuar?')

  // fix_null_team_ids (fk_roto_team / detail_no_score)
  const onRunFix = () => {
    if (!selectedLeagues.length) return
    fixClear()
    fixProc.start({ leagues: selectedLeagues })
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
            onClick={load}
            disabled={loading}
            className="px-3 py-1.5 text-xs rounded bg-blue-600/30 border border-blue-500 text-blue-300 hover:bg-blue-600/40 disabled:opacity-50"
          >
            {loading ? 'Cargando…' : 'Refrescar'}
          </button>
        </div>
      </div>

      <DriverBar driver={driver} busy={driverBusy} onStart={onStartDriver} onStop={onStopDriver} />

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

      {/* Panel: corrección con fix_null_team_ids (FK rota / sin score_entity) */}
      {FIXNULL_KEYS.includes(selected) && (
        <div className="bg-gray-900 rounded p-4 border border-gray-800 flex flex-col gap-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <h3 className="text-sm font-medium text-gray-200">
              Corregir — <span className="text-amber-300">dry-run (no escribe en la BD)</span>
            </h3>
            <span className="text-xs text-gray-500">
              {selectedIds.length} liga(s) seleccionada(s) · {selectableRows.length} mapeable(s)
            </span>
          </div>

          {!driver?.alive && (
            <p className="text-xs text-amber-400 bg-amber-950/30 border border-amber-800 rounded px-3 py-2">
              Iniciá el driver de corrección (arriba) antes de lanzar. La extracción lo reusa.
            </p>
          )}

          <div className="flex items-center gap-2 flex-wrap">
            {!fixProc.isRunning ? (
              <button
                onClick={onRunFix}
                disabled={fixProc.loading || !selectedLeagues.length || !driver?.alive}
                className="px-4 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-40 disabled:cursor-not-allowed rounded text-sm font-semibold text-white"
              >
                ▶ Iniciar corrección (dry-run)
              </button>
            ) : (
              <button
                onClick={fixProc.stop}
                disabled={fixProc.loading}
                className="px-4 py-2 bg-red-700 hover:bg-red-600 disabled:opacity-50 rounded text-sm font-semibold text-white"
              >
                ■ Detener
              </button>
            )}
            <span className="text-xs text-gray-500">
              Estado: {fixProc.status?.status ?? 'stopped'}
              {fixProc.status?.pid && ` · PID ${fixProc.status.pid}`}
            </span>
          </div>

          {fixProc.error && (
            <p className="text-red-400 text-xs bg-red-950/30 border border-red-800 rounded px-3 py-2">
              {fixProc.error}
            </p>
          )}

          <Terminal lines={fixLines} onClear={fixClear} />
        </div>
      )}
    </div>
  )
}
