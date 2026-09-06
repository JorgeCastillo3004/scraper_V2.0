import { useState, useEffect, useCallback, Fragment } from 'react'
import useProcess    from '../hooks/useProcess'
import useWebSocket  from '../hooks/useWebSocket'
import Terminal      from '../components/Terminal'
import DriverBar     from '../components/DriverBar'
import SectionControls from '../components/SectionControls'
import WorkerScreenshots from '../components/WorkerScreenshots'
import {
  getLiveStats, getLiveScreenshots, getSports,
  getLiveDriverStatus, startLiveDriver, stopLiveDriver, setLiveSports, setLiveInterval,
} from '../api/client'

export default function Live() {
  const proc = useProcess('live')
  const { lines, clear } = useWebSocket('live')

  const [allSports,   setAllSports]   = useState([])
  const [sports,      setSports]      = useState([])
  const [matches,     setMatches]     = useState([])
  const [liveShots,   setLiveShots]   = useState([])
  const [interval,    setInterval_]   = useState(60)

  // Driver dedicado de Live (independiente del de correcciones)
  const [driver, setDriver]         = useState(null)
  const [driverBusy, setDriverBusy] = useState(false)

  const toggle = (s) =>
    setSports(prev => {
      const next = prev.includes(s) ? prev.filter(x => x !== s) : [...prev, s]
      // Si el live ya está corriendo, enviar la nueva selección (se aplica al fin del ciclo).
      if (proc.isRunning) setLiveSports(next).catch(() => {})
      return next
    })

  const refreshDriver = useCallback(() => {
    getLiveDriverStatus().then(({ data }) => setDriver(data)).catch(() => {})
  }, [])

  const onStartDriver = async () => {
    setDriverBusy(true)
    try { await startLiveDriver() } catch (_) {}
    finally { setDriverBusy(false); refreshDriver() }
  }
  const onStopDriver = async () => {
    setDriverBusy(true)
    try { await stopLiveDriver() } catch (_) {}
    finally { setDriverBusy(false); refreshDriver() }
  }

  useEffect(() => {
    getSports().then(({ data }) => {
      setAllSports(data)
      setSports(data)
    }).catch(() => {})
    const load = () => getLiveStats().then(({ data }) => setMatches(data)).catch(() => {})
    load()
    refreshDriver()
    const id  = setInterval(load, 10000)
    const idd = setInterval(refreshDriver, 5000)
    return () => { clearInterval(id); clearInterval(idd) }
  }, [refreshDriver])

  useEffect(() => {
    // No pedir capturas si la pestaña está oculta (panel en background = sin gasto).
    const loadShots = () => { if (document.hidden) return
      getLiveScreenshots().then(({ data }) => setLiveShots(data.workers || [])).catch(() => {}) }
    loadShots()
    const shotId = setInterval(loadShots, proc.isRunning ? 5000 : 15000)
    return () => clearInterval(shotId)
  }, [proc.isRunning])

  return (
    <div className="flex flex-col gap-6 max-w-4xl">
      <h2 className="text-lg font-semibold">Live Scores</h2>

      <DriverBar driver={driver} busy={driverBusy} onStart={onStartDriver} onStop={onStopDriver}
                 label="Driver de live:" />

      {!driver?.alive && (
        <p className="text-xs text-amber-400 bg-amber-950/30 border border-amber-800 rounded px-3 py-2">
          Iniciá el driver de live (arriba) antes de lanzar el monitoreo. El script live se reengancha a él.
        </p>
      )}

      <SectionControls proc={proc} startDisabled={!driver?.alive}
                       onStart={() => proc.start({ sports, interval })}>
        <div className="bg-gray-900 rounded p-4 border border-gray-800 flex flex-col gap-4">
          <div>
            <label className="text-xs text-gray-400 mb-2 block">
              Deportes a monitorear
              {proc.isRunning && (
                <span className="text-emerald-400/80 ml-2">· cambios se aplican al próximo ciclo</span>
              )}
            </label>
            <div className="flex gap-2 flex-wrap">
              {allSports.map(s => (
                <button key={s} onClick={() => toggle(s)}
                  className={`px-3 py-1 rounded text-xs font-medium border ${
                    sports.includes(s)
                      ? 'bg-red-600/30 border-red-500 text-red-300'
                      : 'border-gray-700 text-gray-500 hover:border-gray-500'
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="text-xs text-gray-400 mb-2 block">
              Frecuencia de actualización
              {proc.isRunning && (
                <span className="text-emerald-400/80 ml-2">· cambios se aplican al próximo ciclo</span>
              )}
            </label>
            <div className="flex gap-2">
              {[
                { label: '30s',  value: 30  },
                { label: '1 min', value: 60  },
                { label: '2 min', value: 120 },
                { label: '5 min', value: 300 },
              ].map(opt => (
                <button key={opt.value} onClick={() => {
                    setInterval_(opt.value)
                    // Si el live ya corre, aplicar en caliente (pausa del fin de ciclo).
                    if (proc.isRunning) setLiveInterval(opt.value).catch(() => {})
                  }}
                  className={`px-3 py-1 rounded text-xs font-medium border ${
                    interval === opt.value
                      ? 'bg-blue-600/30 border-blue-500 text-blue-300'
                      : 'border-gray-700 text-gray-500 hover:border-gray-500'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </SectionControls>

      {/* Tabla de partidos en vivo */}
      {matches.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-gray-400 mb-2">Partidos hoy</h3>
          <div className="overflow-auto rounded border border-gray-800">
            <table className="w-full text-xs">
              <thead className="bg-gray-900">
                <tr>
                  <th className="p-2 text-left">Liga</th>
                  <th className="p-2 text-left">Partido</th>
                  <th className="p-2 text-center">Resultado</th>
                  <th className="p-2 text-center">Estado</th>
                </tr>
              </thead>
              <tbody>
                {/* Agrupados por deporte: un encabezado de grupo + sus partidos */}
                {Object.entries(
                  matches.reduce((acc, m) => {
                    (acc[m.sport] = acc[m.sport] || []).push(m)
                    return acc
                  }, {})
                )
                  .sort(([a], [b]) => a.localeCompare(b))
                  .map(([sport, list]) => (
                    <Fragment key={sport}>
                      <tr className="bg-gray-900/70">
                        <td colSpan={4} className="p-2 font-semibold text-gray-300 border-t border-gray-700">
                          {sport}
                          <span className="ml-2 text-gray-500 font-normal">· {list.length}</span>
                        </td>
                      </tr>
                      {list.map((m, i) => (
                        <tr key={`${sport}-${i}`} className="border-t border-gray-800">
                          <td className="p-2 text-gray-400">{m.league_name}</td>
                          <td className="p-2">{m.name}</td>
                          <td className="p-2 text-center font-mono">
                            {(() => {
                              // points = -1 (FIXTURE_POINTS) o null = aún sin marcador
                              const h = m.home_score, a = m.away_score
                              const noScore = (v) => v === null || v === undefined || v === -1 || v === '-1'
                              if (noScore(h) && noScore(a)) return <span className="text-gray-600">–</span>
                              return (
                                <span className={m.status === 'LIVE' ? 'text-red-400 font-semibold' : 'text-gray-200'}>
                                  {noScore(h) ? '–' : h} - {noScore(a) ? '–' : a}
                                </span>
                              )
                            })()}
                          </td>
                          <td className="p-2 text-center">
                            <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                              m.status === 'LIVE'
                                ? 'bg-red-600/30 text-red-400'
                                : 'bg-gray-700 text-gray-400'
                            }`}>
                              {m.status}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </Fragment>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <WorkerScreenshots workers={liveShots} running={proc.isRunning} />

      <Terminal lines={lines} onClear={clear} />
    </div>
  )
}
