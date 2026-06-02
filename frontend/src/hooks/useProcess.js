import { useState, useEffect, useCallback } from 'react'
import { getStatus, startSection, stopSection, pauseSection, resumeSection } from '../api/client'

export default function useProcess(section, pollMs = 3000) {
  const [status, setStatus] = useState({ status: 'stopped' })
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  const refresh = useCallback(async () => {
    try {
      const { data } = await getStatus(section)
      setStatus(data)
    } catch (e) {
      setError(e.message)
    }
  }, [section])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, pollMs)
    return () => clearInterval(id)
  }, [refresh, pollMs])

  const run = async (fn) => {
    setLoading(true); setError(null)
    try { await fn(); await refresh() }
    catch (e) { setError(e.response?.data?.detail || e.message) }
    finally { setLoading(false) }
  }

  return {
    status,
    loading,
    error,
    isRunning: status.status === 'running',
    isPaused:  status.status === 'paused',
    isStopped: status.status === 'stopped',
    start:  (params) => run(() => startSection(section, params)),
    stop:   ()       => run(() => stopSection(section)),
    pause:  ()       => run(() => pauseSection(section)),
    resume: ()       => run(() => resumeSection(section)),
    refresh,
  }
}
