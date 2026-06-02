import { useState, useEffect } from 'react'
import useProcess    from '../hooks/useProcess'
import useWebSocket  from '../hooks/useWebSocket'
import Terminal      from '../components/Terminal'
import SectionControls from '../components/SectionControls'
import { getSports } from '../api/client'

export default function Ligas() {
  const proc = useProcess('leagues')
  const { lines, clear } = useWebSocket('leagues')
  const [allSports, setAllSports] = useState([])
  const [sports, setSports] = useState([])

  useEffect(() => {
    getSports().then(({ data }) => {
      setAllSports(data)
      if (sports.length === 0 && data.length > 0) setSports([data[0]])
    }).catch(() => {})
  }, [])

  const toggle = (s) =>
    setSports(prev => prev.includes(s) ? prev.filter(x => x !== s) : [...prev, s])

  return (
    <div className="flex flex-col gap-6 max-w-3xl">
      <h2 className="text-lg font-semibold">Creación de Ligas</h2>

      <SectionControls proc={proc} onStart={() => proc.start({ sports })}>
        <div className="bg-gray-900 rounded p-4 border border-gray-800">
          <label className="text-xs text-gray-400 mb-2 block">Deportes a procesar</label>
          <div className="flex gap-2 flex-wrap">
            {allSports.map(s => (
              <button key={s} onClick={() => toggle(s)}
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
          <p className="text-xs text-gray-600 mt-2">
            Navega el árbol de FlashScore y crea ligas + temporadas en DB
          </p>
        </div>
      </SectionControls>

      <Terminal lines={lines} onClear={clear} />
    </div>
  )
}
