import { useState, useEffect, useMemo } from 'react'
import useProcess    from '../hooks/useProcess'
import useWebSocket  from '../hooks/useWebSocket'
import Terminal      from '../components/Terminal'
import SectionControls from '../components/SectionControls'
import LeagueSelector  from '../components/LeagueSelector'
import { getLeagues, getSports } from '../api/client'

export default function Partidos() {
  const procResults  = useProcess('results')
  const procFixtures = useProcess('fixtures')
  const { lines: logsResults,  clear: clearResults }  = useWebSocket('results')
  const { lines: logsFixtures, clear: clearFixtures } = useWebSocket('fixtures')

  const [tab,      setTab]      = useState('results')
  const [leagues,  setLeagues]  = useState([])
  const [sports,   setSports]   = useState([])
  const [sport,    setSport]    = useState('')
  const [workers,  setWorkers]  = useState(3)
  const [selected, setSelected] = useState([])

  useEffect(() => {
    getSports().then(({ data }) => setSports(data)).catch(() => {})
  }, [])

  useEffect(() => {
    getLeagues(sport || null).then(({ data }) => setLeagues(data)).catch(() => {})
  }, [sport])

  const proc       = tab === 'results' ? procResults  : procFixtures
  const lines      = tab === 'results' ? logsResults  : logsFixtures
  const clearLogs  = tab === 'results' ? clearResults : clearFixtures
  const toggleField = tab === 'results' ? 'extract_results' : 'extract_fixtures'
  const summary = useMemo(() => ({
    leagues: leagues.length,
    teams: leagues.reduce((acc, l) => acc + (l.teams_db ?? 0), 0),
    results: leagues.reduce((acc, l) => acc + (l.results_db ?? 0), 0),
    fixtures: leagues.reduce((acc, l) => acc + (l.fixtures_db ?? 0), 0),
  }), [leagues])

  return (
    <div className="flex flex-col gap-6 max-w-4xl">
      <h2 className="text-lg font-semibold">Partidos</h2>

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-900 p-1 rounded border border-gray-800 w-fit">
        {['results', 'fixtures'].map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-1.5 rounded text-sm font-medium transition-colors ${
              tab === t
                ? 'bg-blue-600 text-white'
                : 'text-gray-400 hover:text-gray-200'
            }`}
          >
            {t === 'results' ? '✅ Results' : '📅 Fixtures'}
          </button>
        ))}
      </div>

      <SectionControls
        proc={proc}
        onStart={() => proc.start({ workers })}
      >
        <div className="bg-gray-900 rounded p-4 border border-gray-800 flex flex-col gap-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="bg-gray-950 border border-gray-800 rounded p-3">
              <p className="text-xs text-gray-500">Ligas</p>
              <p className="text-lg font-semibold">{summary.leagues}</p>
            </div>
            <div className="bg-gray-950 border border-gray-800 rounded p-3">
              <p className="text-xs text-gray-500">Equipos</p>
              <p className="text-lg font-semibold">{summary.teams}</p>
            </div>
            <div className="bg-gray-950 border border-gray-800 rounded p-3">
              <p className="text-xs text-gray-500">Results</p>
              <p className="text-lg font-semibold text-green-400">{summary.results}</p>
            </div>
            <div className="bg-gray-950 border border-gray-800 rounded p-3">
              <p className="text-xs text-gray-500">Fixtures</p>
              <p className="text-lg font-semibold text-blue-400">{summary.fixtures}</p>
            </div>
          </div>

          <div className="flex gap-4 items-end">
            <div>
              <label className="text-xs text-gray-400 mb-1 block">Workers</label>
              <input type="number" min={1} max={5}
                className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm w-24"
                value={workers} onChange={e => setWorkers(Number(e.target.value))}
              />
            </div>
            <div>
              <label className="text-xs text-gray-400 mb-1 block">Filtrar por deporte</label>
              <select
                className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm"
                value={sport} onChange={e => setSport(e.target.value)}
              >
                <option value="">Todos</option>
                {sports.map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
          </div>

          <LeagueSelector
            leagues={leagues}
            showToggles
            toggleField={toggleField}
            columns={{ matchBreakdown: true }}
            onSelectionChange={setSelected}
          />

          <p className="text-xs text-gray-600">
            Los toggles ON/OFF controlan qué ligas procesa <code>paralel_execution.py</code>.
            Activa las ligas deseadas y luego pulsa Iniciar.
          </p>
        </div>
      </SectionControls>

      <Terminal lines={lines} onClear={clearLogs} />
    </div>
  )
}
