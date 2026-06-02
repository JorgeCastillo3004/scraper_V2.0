import { useState } from 'react'
import { toggleLeague } from '../api/client'

const toggleValueKey = (field) => (
  field === 'extract_results' ? 'extract_results'
  : field === 'extract_fixtures' ? 'extract_fixtures'
  : 'teams_extract'
)

const rowId = (league) => `${league.sport}:${league.key}`

export default function LeagueSelector({
  leagues = [],
  onSelectionChange,
  showToggles = false,
  toggleField = 'extract_results',
  onToggleLeague,
  columns = {},
}) {
  const [selected, setSelected] = useState(new Set())
  const [search,   setSearch]   = useState('')
  const [savingKey, setSavingKey] = useState(null)

  const filtered = leagues.filter(l =>
    l.league_name.toLowerCase().includes(search.toLowerCase()) ||
    l.sport.toLowerCase().includes(search.toLowerCase())
  )

  const toggle = (league) => {
    const id = rowId(league)
    const next = new Set(selected)
    next.has(id) ? next.delete(id) : next.add(id)
    setSelected(next)
    onSelectionChange?.(
      leagues.filter(l => next.has(rowId(l))).map(l => ({ sport: l.sport, key: l.key }))
    )
  }

  const toggleAll = () => {
    if (selected.size === filtered.length) {
      setSelected(new Set())
      onSelectionChange?.([])
    } else {
      const allKeys = new Set(filtered.map(rowId))
      setSelected(allKeys)
      onSelectionChange?.(filtered.map(l => ({ sport: l.sport, key: l.key })))
    }
  }

  const handleToggleExtract = async (league) => {
    const current = league[toggleValueKey(toggleField)]
    setSavingKey(`${league.sport}:${league.key}`)
    try {
      await toggleLeague(league.sport, league.key, toggleField, !current)
      await onToggleLeague?.()
    } finally {
      setSavingKey(null)
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <input
        className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm w-full"
        placeholder="Filtrar liga..."
        value={search}
        onChange={e => setSearch(e.target.value)}
      />

      <div className="overflow-auto max-h-64 rounded border border-gray-700">
        <table className="w-full text-xs">
          <thead className="bg-gray-800 sticky top-0">
            <tr>
              <th className="p-2 text-left">
                <input type="checkbox"
                  checked={selected.size === filtered.length && filtered.length > 0}
                  onChange={toggleAll}
                />
              </th>
              <th className="p-2 text-left">Deporte</th>
              <th className="p-2 text-left">Liga</th>
              {columns.expectedTeams && <th className="p-2 text-right">Esperados</th>}
              <th className="p-2 text-right">Equipos</th>
              {columns.matchBreakdown ? (
                <>
                  <th className="p-2 text-right">Results</th>
                  <th className="p-2 text-right">Fixtures</th>
                </>
              ) : (
                <th className="p-2 text-right">Partidos</th>
              )}
              {columns.teamStatus && <th className="p-2 text-left">Checkpoint</th>}
              {showToggles && <th className="p-2 text-center">Habilitada</th>}
            </tr>
          </thead>
          <tbody>
            {filtered.map(l => (
              <tr key={l.key} className="border-t border-gray-800 hover:bg-gray-800/50">
                <td className="p-2">
                  <input type="checkbox"
                    checked={selected.has(rowId(l))}
                    onChange={() => toggle(l)}
                  />
                </td>
                <td className="p-2 text-gray-400">{l.sport}</td>
                <td className="p-2">{l.league_name}</td>
                {columns.expectedTeams && (
                  <td className="p-2 text-right text-gray-400">{l.teams_expected ?? 0}</td>
                )}
                <td className="p-2 text-right text-gray-400">{l.teams_db}</td>
                {columns.matchBreakdown ? (
                  <>
                    <td className="p-2 text-right text-gray-400">{l.results_db ?? 0}</td>
                    <td className="p-2 text-right text-gray-400">{l.fixtures_db ?? 0}</td>
                  </>
                ) : (
                  <td className="p-2 text-right text-gray-400">{l.matches_db}</td>
                )}
                {columns.teamStatus && (
                  <td className="p-2 text-gray-400">
                    {l.teams_status || (l.last_team_created ? `resume: ${l.last_team_created}` : 'pendiente')}
                  </td>
                )}
                {showToggles && (
                  <td className="p-2 text-center">
                    <button
                      onClick={() => handleToggleExtract(l)}
                      disabled={savingKey === `${l.sport}:${l.key}`}
                      className={`px-2 py-0.5 rounded text-xs font-medium ${
                        l[toggleValueKey(toggleField)]
                          ? 'bg-green-600 text-white'
                          : 'bg-gray-700 text-gray-400'
                      } disabled:opacity-50`}
                    >
                      {l[toggleValueKey(toggleField)] ? 'ON' : 'OFF'}
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-gray-500">{selected.size} seleccionadas de {filtered.length}</p>
    </div>
  )
}
