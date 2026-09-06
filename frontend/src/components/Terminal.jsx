import { useEffect, useRef } from 'react'

function classifyLine(line) {
  const u = line.toUpperCase()
  // rojo: errores y "no existe / no encontrada" (chequear NO antes que el positivo)
  if (u.includes('NO ENCONTRADA') || u.includes('NO EXISTENTE') ||
      u.includes('[ERROR]') || u.includes('[SKIP]') || u.includes('[DB-SKIP]')) return 'err'
  // verde: existente / creado / actualizado correctamente / ok
  if (u.includes('EXISTENTE') || u.includes('CREADO') || u.includes('CREATED') ||
      u.includes('CORRECTAMENTE') || u.includes('[OK]')) return 'ok'
  // amarillo: warnings / duplicados
  if (u.includes('[WARN]') || u.includes('[DUP]')) return 'warn'
  // cian: encabezados de datos / progreso (liga / partido / mostrar más / fixtures)
  if (u.includes('[LIGA') || u.includes('[PARTIDO]') ||
      u.includes('[MOSTRAR') || u.includes('[FIXTURES]')) return 'match'
  if (u.includes('[INFO]')) return 'info'
  return ''
}

export default function Terminal({ lines, onClear }) {
  const boxRef = useRef(null)

  // Auto-scroll DENTRO del contenedor del terminal (no mueve la página).
  // Antes usaba scrollIntoView, que scrolleaba la ventana entera al montar /
  // al llegar líneas nuevas → causaba el salto hacia abajo al filtrar.
  useEffect(() => {
    const el = boxRef.current
    if (el) el.scrollTop = el.scrollHeight
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
      <div className="terminal" ref={boxRef}>
        {lines.length === 0
          ? <span className="text-gray-600">Sin actividad...</span>
          : lines.map((line, i) => (
              <div key={i} className={classifyLine(line)}>{line}</div>
            ))
        }
      </div>
    </div>
  )
}
