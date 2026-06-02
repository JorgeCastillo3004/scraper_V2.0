import StatusBadge from './StatusBadge'

export default function SectionControls({ proc, onStart, startDisabled = false, children }) {
  const { isRunning, isPaused, isStopped, loading, error, start, stop, pause, resume, status } = proc

  return (
    <div className="flex flex-col gap-4">
      {/* Header con estado */}
      <div className="flex items-center gap-3">
        <StatusBadge status={status.status} />
        {status.pid && <span className="text-xs text-gray-500">PID {status.pid}</span>}
        {status.started_at && (
          <span className="text-xs text-gray-500">
            Iniciado: {new Date(status.started_at).toLocaleTimeString()}
          </span>
        )}
      </div>

      {/* Botones */}
      <div className="flex gap-2 flex-wrap">
        {isStopped && (
          <button
            onClick={onStart || start}
            disabled={loading || startDisabled}
            className="px-4 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-40 disabled:cursor-not-allowed rounded text-sm font-semibold text-white"
          >
            ▶ Iniciar
          </button>
        )}
        {isRunning && (
          <>
            <button
              onClick={pause}
              disabled={loading}
              className="px-4 py-1.5 bg-yellow-600 hover:bg-yellow-500 disabled:opacity-50 rounded text-sm font-medium"
            >
              ⏸ Pausar
            </button>
            <button
              onClick={stop}
              disabled={loading}
              className="px-4 py-1.5 bg-red-700 hover:bg-red-600 disabled:opacity-50 rounded text-sm font-medium"
            >
              ■ Detener
            </button>
          </>
        )}
        {isPaused && (
          <>
            <button
              onClick={resume}
              disabled={loading}
              className="px-4 py-1.5 bg-green-600 hover:bg-green-500 disabled:opacity-50 rounded text-sm font-medium"
            >
              ▶ Reanudar
            </button>
            <button
              onClick={stop}
              disabled={loading}
              className="px-4 py-1.5 bg-red-700 hover:bg-red-600 disabled:opacity-50 rounded text-sm font-medium"
            >
              ■ Detener
            </button>
          </>
        )}
      </div>

      {/* Contenido adicional (selectores, configuración, etc.) */}
      {children}

      {error && (
        <p className="text-red-400 text-xs bg-red-950/30 border border-red-800 rounded px-3 py-2">
          {error}
        </p>
      )}
    </div>
  )
}
