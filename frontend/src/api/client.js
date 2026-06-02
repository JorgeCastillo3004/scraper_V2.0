import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export const getStatus    = (section) => api.get(`/${section}/status`)
export const getAllStatus  = ()        => api.get('/status/all')
export const getTeamScreenshots = ()   => api.get('/teams/screenshots')
export const getLiveScreenshots = ()   => api.get('/live/screenshots')
export const startSection = (section, params) => api.post(`/${section}/start`, params)
export const stopSection  = (section) => api.post(`/${section}/stop`)
export const pauseSection = (section) => api.post(`/${section}/pause`)
export const resumeSection= (section) => api.post(`/${section}/resume`)

// Leagues cache — TTL 60 s, invalidated on every toggle
let _leaguesCache = null
let _leaguesCacheAt = 0
const LEAGUES_TTL = 60_000

export const invalidateLeaguesCache = () => { _leaguesCache = null }

export const getAllLeagues = async () => {
  const now = Date.now()
  if (_leaguesCache && now - _leaguesCacheAt < LEAGUES_TTL) return _leaguesCache
  const { data } = await api.get('/leagues')
  _leaguesCache = data
  _leaguesCacheAt = now
  return data
}

export const getLeagues   = (sport)   => api.get('/leagues', { params: sport ? { sport } : {} })
export const getSports    = ()        => api.get('/leagues/sports')
export const toggleLeague = async (sport, key, field, value) => {
  const result = await api.patch(`/leagues/${sport}/${encodeURIComponent(key)}`, { field, value })
  invalidateLeaguesCache()
  return result
}

export const getConfig    = ()        => api.get('/config')
export const updateConfig = (data)    => api.patch('/config', data)

export const getStats     = ()        => api.get('/stats')
export const getLiveStats = ()        => api.get('/stats/live')
export const getNewsStats = ()        => api.get('/stats/news')

export const getNewsScheduler = ()    => api.get('/scheduler/news')

export const getInconsistencias = () => api.get('/inconsistencias')

// Driver dedicado (correcciones del panel Inconsistencias)
export const getDriverStatus = () => api.get('/driver/status')
export const startDriver     = () => api.post('/driver/start')
export const stopDriver      = () => api.post('/driver/stop')
