import { useState, useEffect } from 'react'
import useProcess    from '../hooks/useProcess'
import useWebSocket  from '../hooks/useWebSocket'
import Terminal      from '../components/Terminal'
import SectionControls from '../components/SectionControls'
import WorkerScreenshots from '../components/WorkerScreenshots'
import { getLiveStats, getLiveScreenshots, getSports } from '../api/client'

export default function Live() {
  const proc = useProcess('live')
  const { lines, clear } = useWebSocket('live')

  const [allSports,   setAllSports]   = useState([])
  const [sports,      setSports]      = useState([])
  const [matches,     setMatches]     = useState([])
  const [liveShots,   setLiveShots]   = useState([])
  const [interval,    setInterval_]   = useState(60)

  const toggle = (s) =>
    setSports(prev => prev.includes(s) ? prev.filter(x => x !== s) : [...prev, s])

  useEffect(() => {
    getSports().then(({ data }) => {
      setAllSports(data)
      setSports(data)
    }).catch(() => {})
    const load = () => getLiveStats().then(({ data }) => setMatches(data)).catch(() => {})
    load()
    const id = setInterval(load, 10000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    const loadShots = () => getLiveScreenshots().then(({ data }) => setLiveShots(data.workers || [])).catch(() => {})
    loadShots()
    const shotId = setInterval(loadShots, proc.isRunning ? 4000 : 10000)
    return () => clearInterval(shotId)
  }, [proc.isRunning])

  return (
    <div className="flex flex-col gap-6 max-w-4xl">
      <h2 className="text-lg font-semibold">Live Scores</h2>

      <SectionControls proc={proc} onStart={() => proc.start({ sports, interval })}>
        <div className="bg-gray-900 rounded p-4 border border-gray-800 flex flex-col gap-4">
          <div>
            <label className="text-xs text-gray-400 mb-2 block">Deportes a monitorear</label>
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
            <label className="text-xs text-gray-400 mb-2 block">Frecuencia de actualización</label>
            <div className="flex gap-2">
              {[
                { label: '30s',  value: 30  },
                { label: '1 min', value: 60  },
                { label: '2 min', value: 120 },
                { label: '5 min', value: 300 },
              ].map(opt => (
                <button key={opt.value} onClick={() => setInterval_(opt.value)}
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
                  <th className="p-2 text-left">Deporte</th>
                  <th className="p-2 text-left">Liga</th>
                  <th className="p-2 text-left">Partido</th>
                  <th className="p-2 text-center">Estado</th>
                </tr>
              </thead>
              <tbody>
                {matches.map((m, i) => (
                  <tr key={i} className="border-t border-gray-800">
                    <td className="p-2 text-gray-500">{m.sport}</td>
                    <td className="p-2 text-gray-400">{m.league_name}</td>
                    <td className="p-2">{m.name}</td>
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
