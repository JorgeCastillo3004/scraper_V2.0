import { useState, useEffect, useCallback } from 'react'
import {
  getLeaguesStatus, getDbHistoryList, getDbHistory, takeDbHistorySnapshot,
} from '../api/client'

// Color del estado por liga según cobertura.
function estadoClass(r) {
  if (!r || r.estado === '—') return 'text-gray-500'
  if (r.estado.startsWith('OK')) return 'text-green-400'
  if (r.estado.startsWith('faltan')) return 'text-amber-400'
  return 'text-gray-300'
}

export default function DbHistoryPanel() {
  // ── Estado por liga (desde logs) ──
  const [leagues, setLeagues] = useState([])
  const loadLeagues = useCallback(() => {
    getLeaguesStatus().then(({ data }) => setLeagues(data.leagues || [])).catch(() => {})
  }, [])

  // ── Visor de db_history ──
  const [snaps, setSnaps]   = useState([])
  const [idx, setIdx]       = useState(null)
  const [text, setText]     = useState('')
  const [busy, setBusy]     = useState(false)

  const loadList = useCallback(async (gotoLast = true) => {
    try {
      const { data } = await getDbHistoryList()
      const list = data.snapshots || []
      setSnaps(list)
      if (gotoLast && list.length) setIdx(list.length - 1)
    } catch (_) {}
  }, [])

  // Cargar el texto del snapshot seleccionado.
  useEffect(() => {
    if (idx == null) return
    getDbHistory(idx).then(({ data }) => setText(data.text || '')).catch(() => setText(''))
  }, [idx])

  useEffect(() => {
    loadLeagues()
    loadList(true)
    // refresco suave: el backend toma un snapshot al terminar la extracción.
    const id = setInterval(() => { loadLeagues(); loadList(false) }, 30_000)
    return () => clearInterval(id)
  }, [loadLeagues, loadList])

  const cur = snaps.find((s) => s.idx === idx)
  const canPrev = idx != null && idx > 0
  const canNext = idx != null && idx < snaps.length - 1

  const onSnapshot = async () => {
    setBusy(true)
    try {
      const { data } = await takeDbHistorySnapshot()   // consulta remoto (solo SELECT)
      await loadList(false)
      setIdx(data.idx)
    } catch (_) {} finally { setBusy(false) }
  }

  return (
    <div className="flex flex-col gap-4 mt-2">
      {/* ── Estado por liga (última ejecución + cobertura desde logs) ── */}
      <div className="bg-gray-900 rounded p-4 border border-gray-800">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium text-gray-200">Estado por liga (últimas ejecuciones)</h3>
          <button onClick={loadLeagues}
            className="text-xs text-gray-500 hover:text-gray-300 px-2 py-0.5 rounded border border-gray-700">
            ↻ Refrescar
          </button>
        </div>
        <div className="max-h-72 overflow-auto">
          <table className="w-full text-xs">
            <thead className="text-gray-500 sticky top-0 bg-gray-900">
              <tr className="text-left">
                <th className="py-1">Liga</th>
                <th className="py-1">Deporte</th>
                <th className="py-1">Última ejecución</th>
                <th className="py-1">Cobertura</th>
                <th className="py-1">Estado</th>
              </tr>
            </thead>
            <tbody>
              {leagues.length === 0
                ? <tr><td colSpan={5} className="py-2 text-gray-600">Sin datos en los logs…</td></tr>
                : leagues.map((r) => (
                    <tr key={r.liga} className="border-t border-gray-800">
                      <td className="py-1 text-gray-200">{r.liga}</td>
                      <td className="py-1 text-gray-400">{r.sport}</td>
                      <td className="py-1 text-gray-400 font-mono">{r.last_run}</td>
                      <td className="py-1 text-blue-300 font-mono">{r.cobertura}</td>
                      <td className={`py-1 ${estadoClass(r)}`}>{r.estado}</td>
                    </tr>
                  ))
              }
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Visor de db_history con navegación ◀ ▶ ── */}
      <div className="bg-gray-900 rounded p-4 border border-gray-800">
        <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
          <h3 className="text-sm font-medium text-gray-200">Historial de la BD (db_history)</h3>
          <div className="flex items-center gap-2">
            <button onClick={() => canPrev && setIdx(idx - 1)} disabled={!canPrev}
              className="px-2 py-0.5 rounded border border-gray-700 text-gray-300 disabled:opacity-30">◀</button>
            <span className="text-xs text-gray-400 font-mono min-w-[8rem] text-center">
              {idx == null ? '—' : `${idx + 1} / ${snaps.length}`}
              {cur?.timestamp ? ` · ${cur.timestamp}` : ''}
            </span>
            <button onClick={() => canNext && setIdx(idx + 1)} disabled={!canNext}
              className="px-2 py-0.5 rounded border border-gray-700 text-gray-300 disabled:opacity-30">▶</button>
            <button onClick={() => loadList(true)}
              className="text-xs text-gray-500 hover:text-gray-300 px-2 py-0.5 rounded border border-gray-700">↻</button>
            <button onClick={onSnapshot} disabled={busy}
              className="text-xs px-2 py-0.5 rounded border border-emerald-700 text-emerald-300 hover:bg-emerald-950/40 disabled:opacity-40">
              {busy ? 'Tomando…' : 'Tomar snapshot'}
            </button>
          </div>
        </div>
        <pre className="terminal whitespace-pre overflow-auto max-h-96 text-xs">{text || 'Sin datos…'}</pre>
      </div>
    </div>
  )
}
