// Barra de control de un driver Selenium dedicado del panel (Iniciar / Matar +
// estado). Reutilizada por Inconsistencias (driver de corrección) y Live (driver
// de live). El cableado a los endpoints lo pasa cada página por props.
export default function DriverBar({ driver, busy, onStart, onStop, label = 'Driver:',
                                    headlessPref, onToggleHeadless }) {
  const alive = driver?.alive
  const launching = driver?.launcher_running && !driver?.session_ready
  return (
    <div className="flex items-center gap-3 flex-wrap bg-gray-900 rounded p-3 border border-gray-800">
      <span className="text-sm text-gray-300 font-medium">{label}</span>
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
      {onToggleHeadless && (
        <label
          className="text-xs text-gray-400 flex items-center gap-1 cursor-pointer select-none"
          title="Sin ventana (menos RAM). Se aplica al PRÓXIMO (re)lanzamiento del driver."
        >
          <input
            type="checkbox"
            checked={!!headlessPref}
            onChange={(e) => onToggleHeadless(e.target.checked)}
            disabled={busy}
          />
          headless (próx. inicio)
        </label>
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
