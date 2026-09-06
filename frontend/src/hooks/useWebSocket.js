import { useState, useEffect, useRef, useCallback } from 'react'

const WS_BASE = `ws://${window.location.host}`

export default function useWebSocket(section) {
  const [lines, setLines]   = useState([])
  const [status, setStatus] = useState('disconnected')
  const wsRef  = useRef(null)
  const timerRef = useRef(null)

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket(`${WS_BASE}/ws/${section}/logs`)
    wsRef.current = ws
    setStatus('connecting')

    ws.onopen  = () => setStatus('connected')
    ws.onclose = () => {
      setStatus('disconnected')
      // Reconexión SOLO si la pestaña está visible (en background no reconectamos
      // ni streameamos: el panel corre mucho tiempo y no debe gastar en background).
      if (!document.hidden) timerRef.current = setTimeout(connect, 4000)
    }
    ws.onerror = () => ws.close()

    ws.onmessage = ({ data }) => {
      try {
        const parsed = JSON.parse(data)
        if (parsed.type === 'status') { setStatus(parsed.value); return }
      } catch (_) {}
      setLines(prev => [...prev.slice(-499), data])   // tope 500 líneas (no crece)
    }
  }, [section])

  useEffect(() => {
    // Cerrar la conexión cuando la pestaña se oculta; reconectar al volver.
    const onVis = () => {
      if (document.hidden) {
        clearTimeout(timerRef.current)
        wsRef.current?.close()
      } else {
        connect()
      }
    }
    document.addEventListener('visibilitychange', onVis)
    if (!document.hidden) connect()
    return () => {
      document.removeEventListener('visibilitychange', onVis)
      clearTimeout(timerRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  const clear = () => setLines([])
  return { lines, status, clear }
}
