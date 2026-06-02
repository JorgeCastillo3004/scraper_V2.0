import { useState, useEffect } from 'react'
import useProcess    from '../hooks/useProcess'
import useWebSocket  from '../hooks/useWebSocket'
import Terminal      from '../components/Terminal'
import SectionControls from '../components/SectionControls'
import { getSports } from '../api/client'

export default function Jugadores() {
  const proc = useProcess('players')
  const { lines, clear } = useWebSocket('players')

  const [sports,  setSports]  = useState([])
  const [sport,   setSport]   = useState('')
  const [workers, setWorkers] = useState(2)

  useEffect(() => {
    getSports().then(({ data }) => {
      setSports(data)
      if (data.length > 0) setSport(data[0])
    }).catch(() => {})
  }, [])

  return (
    <div className="flex flex-col gap-6 max-w-3xl">
      <h2 className="text-lg font-semibold">Jugadores</h2>

      <SectionControls
        proc={proc}
        onStart={() => proc.start({ workers, sports: [sport] })}
      >
        <div className="bg-gray-900 rounded p-4 border border-gray-800 flex gap-4 items-end">
          <div>
            <label className="text-xs text-gray-400 mb-1 block">Workers</label>
            <input type="number" min={1} max={5}
              className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm w-24"
              value={workers} onChange={e => setWorkers(Number(e.target.value))}
            />
          </div>
          <div>
            <label className="text-xs text-gray-400 mb-1 block">Deporte</label>
            <select
              className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm"
              value={sport} onChange={e => setSport(e.target.value)}
            >
              {sports.map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          <p className="text-xs text-gray-600 self-end pb-2">
            Usa <code>paralel_players.py</code> (milestone6)
          </p>
        </div>
      </SectionControls>

      <Terminal lines={lines} onClear={clear} />
    </div>
  )
}
