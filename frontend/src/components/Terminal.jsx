import { useEffect, useRef } from 'react'

function classifyLine(line) {
  if (line.includes('[ERROR]')) return 'err'
  if (line.includes('[WARN]'))  return 'warn'
  if (line.includes('[INFO]'))  return 'info'
  return ''
}

export default function Terminal({ lines, onClear }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines])

  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between items-center">
        <span className="text-xs text-gray-500">Logs ({lines.length})</span>
        {onClear && (
          <button onClick={onClear}
            className="text-xs text-gray-500 hover:text-gray-300 px-2 py-0.5 rounded border border-gray-700">
            Limpiar
          </button>
        )}
      </div>
      <div className="terminal">
        {lines.length === 0
          ? <span className="text-gray-600">Sin actividad...</span>
          : lines.map((line, i) => (
              <div key={i} className={classifyLine(line)}>{line}</div>
            ))
        }
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
