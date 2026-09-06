import { useState, useEffect, useCallback, useMemo } from 'react'
import useProcess    from '../hooks/useProcess'
import useWebSocket  from '../hooks/useWebSocket'
import Terminal      from '../components/Terminal'
import SectionControls from '../components/SectionControls'
import LeagueSelector  from '../components/LeagueSelector'
import WorkerScreenshots from '../components/WorkerScreenshots'
import { getAllLeagues, getSports, getTeamScreenshots, toggleLeague, invalidateLeaguesCache } from '../api/client'

export default function Equipos() {
  const proc = useProcess('teams')
  const { lines, clear } = useWebSocket('teams')

  const [allLeagues, setAllLeagues] = useState([])
  const [sports,     setSports]     = useState([])
  const [sport,      setSport]      = useState('')
  const [workers,    setWorkers]    = useState(2)
  const [selected,   setSelected]   = useState([])
  const [teamThresholdEnabled, setTeamThresholdEnabled] = useState(false)
  const [teamThreshold, setTeamThreshold] = useState(0)
  const [workerShots, setWorkerShots] = useState([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    getSports().then(({ data }) => setSports(data)).catch(() => {})
  }, [])

  const refreshLeagues = useCallback(async (invalidate = false) => {
    if (invalidate) invalidateLeaguesCache()
    setLoading(true)
    try {
      const data = await getAllLeagues()
      setAllLeagues(data)
    } catch { /* ignore */ } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refreshLeagues()
  }, [])

  useEffect(() => {
    let cancelled = false

    const refreshShots = async () => {
      if (document.hidden) return   // sin gasto si la pestaña está oculta
      try {
        const { data } = await getTeamScreenshots()
        if (!cancelled) setWorkerShots(data.workers || [])
      } catch {
        if (!cancelled) setWorkerShots([])
      }
    }

    refreshShots()
    const id = setInterval(refreshShots, proc.isRunning ? 5000 : 15000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [proc.isRunning])

  useEffect(() => {
    setSelected([])
  }, [sport, teamThresholdEnabled, teamThreshold])

  // All filtering is client-side — no extra API calls when switching sport/threshold
  const leagues = useMemo(() => {
    let list = sport ? allLeagues.filter(l => l.sport === sport) : allLeagues
    if (teamThresholdEnabled) list = list.filter(l => (l.teams_db ?? 0) <= teamThreshold)
    return list
  }, [allLeagues, sport, teamThresholdEnabled, teamThreshold])

  const summary = useMemo(() => {
    const base = sport ? allLeagues.filter(l => l.sport === sport) : allLeagues
    const enabled = base.filter(l => l.teams_extract)
    const pending = enabled.filter(l => (l.teams_db ?? 0) < (l.teams_expected ?? 0))
    return {
      total: base.length,
      visible: leagues.length,
      enabled: enabled.length,
      pending: pending.length,
      expectedTeams: enabled.reduce((acc, l) => acc + (l.teams_expected ?? 0), 0),
      dbTeams: enabled.reduce((acc, l) => acc + (l.teams_db ?? 0), 0),
      results: enabled.reduce((acc, l) => acc + (l.results_db ?? 0), 0),
      fixtures: enabled.reduce((acc, l) => acc + (l.fixtures_db ?? 0), 0),
    }
  }, [allLeagues, leagues])

  const selectedSports = [...new Set(selected.map(l => l.sport))]
  const startSports = sport ? [sport] : selectedSports.length === 1 ? selectedSports : []

  const setSelectedEnabled = async (value) => {
    await Promise.all(
      selected.map(l => toggleLeague(l.sport, l.key, 'teams_creation', value))
    )
    setSelected([])
    await refreshLeagues(true)
  }

  const startTeams = () => {
    return proc.start({
      workers,
      sports: startSports,
      leagues: selected,
    })
  }

  return (
    <div className="flex flex-col gap-6 max-w-4xl">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Creación de Equipos</h2>
        <button
          onClick={() => refreshLeagues(true)}
          disabled={loading}
          className="px-3 py-1 text-xs rounded border border-gray-700 hover:border-gray-500 text-gray-400 disabled:opacity-50"
        >
          {loading ? 'Cargando...' : '↻ Actualizar'}
        </button>
      </div>

      <SectionControls
        proc={proc}
        onStart={startTeams}
        startDisabled={selected.length === 0}
      >
        <div className="bg-gray-900 rounded p-4 border border-gray-800 flex flex-col gap-4">
          <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
            <div className="bg-gray-950 border border-gray-800 rounded p-3">
              <p className="text-xs text-gray-500">Ligas</p>
              <p className="text-lg font-semibold">
                {teamThresholdEnabled ? `${summary.visible} / ${summary.total}` : summary.total}
              </p>
            </div>
            <div className="bg-gray-950 border border-gray-800 rounded p-3">
              <p className="text-xs text-gray-500">Habilitadas</p>
              <p className="text-lg font-semibold text-green-400">{summary.enabled}</p>
            </div>
            <div className="bg-gray-950 border border-gray-800 rounded p-3">
              <p className="text-xs text-gray-500">Pendientes</p>
              <p className="text-lg font-semibold text-yellow-400">{summary.pending}</p>
            </div>
            <div className="bg-gray-950 border border-gray-800 rounded p-3">
              <p className="text-xs text-gray-500">Equipos DB</p>
              <p className="text-lg font-semibold">{summary.dbTeams}</p>
            </div>
            <div className="bg-gray-950 border border-gray-800 rounded p-3">
              <p className="text-xs text-gray-500">Esperados</p>
              <p className="text-lg font-semibold">{summary.expectedTeams}</p>
            </div>
            <div className="bg-gray-950 border border-gray-800 rounded p-3">
              <p className="text-xs text-gray-500">Results / Fixtures</p>
              <p className="text-lg font-semibold">{summary.results} / {summary.fixtures}</p>
            </div>
          </div>

          <div className="flex gap-4 items-end flex-wrap">
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
            <label className="flex items-center gap-2 h-9 text-sm text-gray-300">
              <input
                type="checkbox"
                checked={teamThresholdEnabled}
                onChange={e => setTeamThresholdEnabled(e.target.checked)}
              />
              Filtrar por equipos
            </label>
            <div>
              <label className="text-xs text-gray-400 mb-1 block">Máx. equipos DB</label>
              <input
                type="number"
                min={0}
                disabled={!teamThresholdEnabled}
                className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm w-32 disabled:opacity-50"
                value={teamThreshold}
                onChange={e => setTeamThreshold(Math.max(0, Number(e.target.value)))}
              />
            </div>
            <button
              type="button"
              disabled={selected.length === 0}
              onClick={() => setSelectedEnabled(true)}
              className="px-3 py-2 bg-green-600 hover:bg-green-500 disabled:opacity-40 disabled:cursor-not-allowed rounded text-sm font-semibold text-white"
            >
              Habilitar seleccionadas
            </button>
            <button
              type="button"
              disabled={selected.length === 0}
              onClick={() => setSelectedEnabled(false)}
              className="px-3 py-2 bg-gray-600 hover:bg-gray-500 disabled:opacity-40 disabled:cursor-not-allowed rounded text-sm font-semibold text-white"
            >
              Deshabilitar seleccionadas
            </button>
          </div>

          <LeagueSelector
            key={`${sport}:${teamThresholdEnabled}:${teamThreshold}`}
            leagues={leagues}
            showToggles
            toggleField="teams_creation"
            columns={{ expectedTeams: true, teamStatus: true, matchBreakdown: true }}
            onSelectionChange={setSelected}
            onToggleLeague={() => refreshLeagues(true)}
          />

          <p className="text-xs text-gray-600">
            Los toggles ON/OFF escriben <code>teams_creation.extract</code>. El filtro de equipos muestra ligas con <code>teams_db</code> menor o igual al máximo indicado.
          </p>
          <p className="text-xs text-gray-600">
            Al iniciar, se procesan solo las ligas seleccionadas en la tabla. El backend arma el diccionario real tomando la metadata desde <code>leagues_info.json</code>.
          </p>
        </div>
      </SectionControls>

      <WorkerScreenshots workers={workerShots} running={proc.isRunning} />

      <Terminal lines={lines} onClear={clear} />
    </div>
  )
}
