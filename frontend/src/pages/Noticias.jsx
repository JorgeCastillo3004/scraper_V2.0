import { useState, useEffect } from 'react'
import useProcess    from '../hooks/useProcess'
import useWebSocket  from '../hooks/useWebSocket'
import Terminal      from '../components/Terminal'
import SectionControls from '../components/SectionControls'
import { getConfig, updateConfig, getSports, getNewsStats, getNewsScheduler } from '../api/client'

const fmtFecha = (iso) => {
  if (!iso) return null
  const d = new Date(iso)
  if (isNaN(d)) return iso
  return d.toLocaleString('es-ES', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export default function Noticias() {
  const proc = useProcess('news')
  const { lines, clear } = useWebSocket('news')

  const [allSports, setAllSports] = useState([])
  const [sports,   setSports]   = useState([])
  const [days,     setDays]     = useState(31)
  const [autoEnabled, setAutoEnabled] = useState(false)
  const [everyHours,  setEveryHours]  = useState(6)
  const [newsStats, setNewsStats] = useState(null)
  const [sched,     setSched]     = useState(null)
  const [saved,     setSaved]     = useState(false)

  const refreshSched = () =>
    getNewsScheduler().then(({ data }) => setSched(data)).catch(() => {})

  useEffect(() => {
    getNewsStats().then(({ data }) => setNewsStats(data)).catch(() => {})
    refreshSched()
    const t = setInterval(refreshSched, 15000)  // refrescar estado del scheduler

    // Resolvemos deportes y config juntos para aplicar bien el default.
    Promise.all([
      getSports().then(({ data }) => data).catch(() => []),
      getConfig().then(({ data }) => data).catch(() => null),
    ]).then(([sportsData, cfgData]) => {
      setAllSports(sportsData)
      const cfg = cfgData?.EXTRACT_NEWS
      if (cfg?.MAX_OLDER_DATE_ALLOWED) setDays(cfg.MAX_OLDER_DATE_ALLOWED)
      if (typeof cfg?.ENABLED === 'boolean') setAutoEnabled(cfg.ENABLED)
      if (cfg?.EVERY_HOURS) setEveryHours(cfg.EVERY_HOURS)
      // Por defecto: TODOS los deportes seleccionados, salvo que CONFIG.json
      // ya tenga una selección guardada (entonces respetamos esa).
      if (cfg?.SPORTS && cfg.SPORTS.length) setSports(cfg.SPORTS)
      else setSports(sportsData)
    })

    return () => clearInterval(t)
  }, [])

  const toggleSport = (s) =>
    setSports(prev => prev.includes(s) ? prev.filter(x => x !== s) : [...prev, s])

  const saveSchedule = async () => {
    await updateConfig({ EXTRACT_NEWS: {
      ENABLED: autoEnabled,
      EVERY_HOURS: everyHours,
      SPORTS: sports,
      MAX_OLDER_DATE_ALLOWED: days,
    } })
    setSaved(true)
    setTimeout(() => setSaved(false), 2500)
    refreshSched()
  }

  return (
    <div className="flex flex-col gap-6 max-w-3xl">
      <div className="flex items-baseline gap-3 flex-wrap">
        <h2 className="text-lg font-semibold">Noticias</h2>
        {newsStats && !newsStats.error && (
          <span className="text-xs text-gray-400">
            Última noticia extraída:{' '}
            <span className="text-gray-200 font-medium">
              {fmtFecha(newsStats.last_published) ?? 'sin noticias en la BD'}
            </span>
            {typeof newsStats.total === 'number' && (
              <span className="text-gray-500"> · {newsStats.total.toLocaleString('es-ES')} en total</span>
            )}
          </span>
        )}
      </div>

      <SectionControls
        proc={proc}
        onStart={() => proc.start({ sports, days })}
      >
        {/* Configuración */}
        <div className="grid grid-cols-2 gap-4 bg-gray-900 rounded p-4 border border-gray-800">
          {/* Programación automática */}
          <div className="col-span-2 flex flex-col gap-2 bg-gray-950/40 rounded p-3 border border-gray-800">
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox"
                checked={autoEnabled}
                onChange={e => setAutoEnabled(e.target.checked)}
              />
              <span className="font-medium">Extracción automática de noticias</span>
            </label>
            <div className="flex items-center gap-2 text-sm">
              <span className="text-gray-400">Ejecutar cada</span>
              <input type="number" min={1} max={168} step={1}
                className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm w-24 disabled:opacity-40"
                value={everyHours}
                disabled={!autoEnabled}
                onChange={e => setEveryHours(Number(e.target.value))}
              />
              <span className="text-gray-400">horas</span>
            </div>
            {sched && (
              <div className="text-xs text-gray-500 mt-1">
                {sched.enabled ? (
                  <>
                    Estado: <span className="text-green-400">activo</span>
                    {sched.next_run && <> · próxima ejecución: <span className="text-gray-300">{fmtFecha(sched.next_run)}</span></>}
                    {sched.last_run && <> · última: <span className="text-gray-300">{fmtFecha(sched.last_run)}</span></>}
                    {sched.news_running && <> · <span className="text-blue-400">ejecutándose ahora</span></>}
                  </>
                ) : (
                  <>Estado: <span className="text-gray-400">desactivado</span></>
                )}
                {sched.last_error && <div className="text-red-400 mt-0.5">último error: {sched.last_error}</div>}
              </div>
            )}
          </div>

          <div>
            <label className="text-xs text-gray-400 mb-1 block">Días hacia atrás</label>
            <input type="number" min={1} max={90}
              className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm w-full"
              value={days}
              onChange={e => setDays(Number(e.target.value))}
            />
          </div>

          <div className="col-span-2">
            <label className="text-xs text-gray-400 mb-2 block">Deportes</label>
            <div className="flex gap-2 flex-wrap">
              {allSports.map(s => (
                <button key={s}
                  onClick={() => toggleSport(s)}
                  className={`px-3 py-1 rounded text-xs font-medium border ${
                    sports.includes(s)
                      ? 'bg-blue-600/30 border-blue-500 text-blue-300'
                      : 'border-gray-700 text-gray-500 hover:border-gray-500'
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          <div className="col-span-2 flex justify-end items-center gap-3">
            {saved && <span className="text-xs text-green-400">Guardado ✓</span>}
            <button onClick={saveSchedule}
              className="px-4 py-1.5 bg-gray-700 hover:bg-gray-600 rounded text-sm">
              Guardar configuración
            </button>
          </div>
        </div>
      </SectionControls>

      <Terminal lines={lines} onClear={clear} />
    </div>
  )
}
