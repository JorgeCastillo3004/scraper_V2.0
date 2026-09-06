import { useState, useEffect, useCallback } from 'react'
import { getDriverRegistry, startDriver, stopDriver } from '../api/client'

const STATUS_STYLE = {
  ready:  'bg-emerald-600/20 text-emerald-300 border-emerald-600/40',
  busy:   'bg-amber-600/20 text-amber-300 border-amber-600/40',
  closed: 'bg-gray-600/20 text-gray-400 border-gray-600/40',
}

const fmtTime = (iso) => {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleString() } catch { return iso }
}

export default function Drivers() {
  const [drivers, setDrivers] = useState([])
  const [updatedAt, setUpdatedAt] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    if (document.hidden) return
    getDriverRegistry()
      .then(({ data }) => {
        setDrivers(Object.values(data.drivers || {}))
        setUpdatedAt(data.updated_at)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(() => { if (!document.hidden) load() }, 5000)
    const onVis = () => { if (!document.hidden) load() }
    document.addEventListener('visibilitychange', onVis)
    return () => { clearInterval(id); document.removeEventListener('visibilitychange', onVis) }
  }, [load])

  // El driver compartido lo crea/recrea el usuario (siempre confirmado).
  const createShared = async () => {
    if (!window.confirm('¿Crear el driver compartido (de corrección)?\n\n'
      + 'Lanza Firefox + login (~10-40s). Lo usan los flujos de corrección/creación.')) return
    setBusy(true)
    try { await startDriver() } catch (_) {} finally { setBusy(false); load() }
  }
  const stopShared = async () => {
    if (!window.confirm('¿Cerrar el driver compartido (de corrección)?\n\n'
      + 'SIGTERM limpio (driver.quit()), nunca pkill. Libera su RAM.')) return
    setBusy(true)
    try { await stopDriver() } catch (_) {} finally { setBusy(false); load() }
  }

  const shared = drivers.filter(d => d.role === 'shared')
  const noneAvailable = shared.length > 0 && !shared.some(d => d.status === 'ready' || d.status === 'busy')

  return (
    <div className="flex flex-col gap-6 max-w-4xl">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">🖥️ Drivers</h2>
        <span className="text-xs text-gray-500">
          {updatedAt ? `actualizado ${fmtTime(updatedAt)}` : ''}
        </span>
      </div>

      <p className="text-xs text-gray-500 max-w-2xl">
        Registro central de todos los drivers Selenium. El <b>live</b> tiene driver dedicado;
        el <b>compartido</b> (corrección) lo usan por turnos los flujos de corrección/creación
        (lock por <code>owner</code>). La creación de drivers siempre se confirma acá.
      </p>

      {/* Aviso: ningún driver compartido disponible */}
      {noneAvailable && (
        <div className="bg-amber-950/30 border border-amber-800 rounded px-3 py-2 text-xs text-amber-300 flex items-center justify-between gap-3">
          <span>No hay driver compartido disponible. Creá uno para que los flujos de corrección/creación puedan trabajar.</span>
          <button onClick={createShared} disabled={busy}
            className="px-3 py-1 rounded bg-emerald-700/50 border border-emerald-600 text-emerald-200 hover:bg-emerald-700/70 disabled:opacity-40 shrink-0">
            Crear driver
          </button>
        </div>
      )}

      <div className="overflow-auto rounded border border-gray-800">
        <table className="w-full text-xs">
          <thead className="bg-gray-900">
            <tr>
              <th className="p-2 text-left">Driver</th>
              <th className="p-2 text-left">Rol</th>
              <th className="p-2 text-center">Estado</th>
              <th className="p-2 text-left">En uso por</th>
              <th className="p-2 text-center">PID</th>
              <th className="p-2 text-center">Puerto</th>
              <th className="p-2 text-left">Último uso</th>
              <th className="p-2 text-right">Acciones</th>
            </tr>
          </thead>
          <tbody>
            {drivers.length === 0 && (
              <tr><td colSpan={8} className="p-3 text-center text-gray-600">Sin drivers registrados</td></tr>
            )}
            {drivers.map(d => (
              <tr key={d.id} className="border-t border-gray-800">
                <td className="p-2 font-medium text-gray-200">{d.id}</td>
                <td className="p-2 text-gray-400">{d.role}</td>
                <td className="p-2 text-center">
                  <span className={`px-2 py-0.5 rounded text-[10px] border ${STATUS_STYLE[d.status] || STATUS_STYLE.closed}`}>
                    {d.status}
                  </span>
                </td>
                <td className="p-2 text-gray-400">{d.owner || '—'}</td>
                <td className="p-2 text-center text-gray-500">{d.launcher_pid || '—'}</td>
                <td className="p-2 text-center text-gray-500">{d.port || '—'}</td>
                <td className="p-2 text-gray-500">{fmtTime(d.last_used)}</td>
                <td className="p-2 text-right whitespace-nowrap">
                  {d.role === 'shared' && d.status === 'closed' && (
                    <button onClick={createShared} disabled={busy}
                      className="text-[11px] px-2 py-1 rounded bg-emerald-700/40 border border-emerald-700 text-emerald-300 hover:bg-emerald-700/60 disabled:opacity-40">
                      Crear
                    </button>
                  )}
                  {d.role === 'shared' && d.status !== 'closed' && (
                    <button onClick={stopShared} disabled={busy || d.status === 'busy'}
                      title={d.status === 'busy' ? 'En uso: liberalo antes de cerrar' : 'Cerrar (SIGTERM limpio)'}
                      className="text-[11px] px-2 py-1 rounded bg-gray-700/40 border border-gray-700 text-gray-300 hover:bg-gray-700/60 disabled:opacity-40">
                      Cerrar
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
