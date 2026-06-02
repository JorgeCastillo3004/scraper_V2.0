export default function WorkerScreenshots({ workers = [], running = false }) {
  return (
    <div className="bg-gray-900 rounded p-4 border border-gray-800 flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-gray-200">Capturas del scraper</h3>
        <span className="text-xs text-gray-500">
          {running ? 'Actualizando...' : 'Última captura disponible'}
        </span>
      </div>

      {workers.length === 0 ? (
        <div className="border border-dashed border-gray-700 rounded p-6 text-sm text-gray-500">
          Aún no hay capturas de workers.
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {workers.map((worker) => (
            <div key={worker.worker_id} className="border border-gray-800 rounded overflow-hidden bg-gray-950 w-full">
              <div className="px-3 py-2 border-b border-gray-800 flex flex-col gap-1">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium text-gray-200">Worker {worker.worker_id}</span>
                  <span className="text-xs text-gray-500">
                    {worker.captured_at ? new Date(worker.captured_at).toLocaleTimeString() : '—'}
                  </span>
                </div>
                <p className="text-xs text-gray-400">{worker.league || '—'}</p>
                <p className="text-xs text-gray-500">{worker.label || 'snapshot'}</p>
              </div>
              <div className="overflow-y-auto max-h-[72vh]">
                <img
                  src={worker.image_url}
                  alt={`Worker ${worker.worker_id}`}
                  className="block w-full"
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
