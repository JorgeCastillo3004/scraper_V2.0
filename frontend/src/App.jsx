import { Routes, Route, NavLink } from 'react-router-dom'
import Noticias  from './pages/Noticias'
import Ligas     from './pages/Ligas'
import Equipos   from './pages/Equipos'
import Partidos  from './pages/Partidos'
import Jugadores from './pages/Jugadores'
import Live      from './pages/Live'
import Inconsistencias from './pages/Inconsistencias'
import Drivers   from './pages/Drivers'

const NAV = [
  { to: '/noticias',         label: '📰 Noticias'        },
  { to: '/ligas',            label: '🏆 Ligas'           },
  { to: '/equipos',          label: '👥 Equipos'         },
  { to: '/partidos',         label: '⚽ Partidos'        },
  { to: '/jugadores',        label: '🧑 Jugadores'       },
  { to: '/live',             label: '🔴 Live'            },
  { to: '/inconsistencias',  label: '🩺 Inconsistencias' },
  { to: '/drivers',          label: '🖥️ Drivers'         },
]

export default function App() {
  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <nav className="w-48 bg-gray-900 border-r border-gray-800 flex flex-col py-6 gap-1 shrink-0">
        <div className="px-4 mb-4">
          <h1 className="text-sm font-bold text-gray-200">scraper_V2.0</h1>
          <p className="text-xs text-gray-500">Control Panel</p>
        </div>
        {NAV.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `px-4 py-2 text-sm rounded mx-2 transition-colors ${
                isActive
                  ? 'bg-blue-600/30 text-blue-300 font-medium'
                  : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
              }`
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Contenido */}
      <main className="flex-1 p-6 overflow-auto">
        <Routes>
          <Route path="/"          element={<Live />} />
          <Route path="/noticias"  element={<Noticias />} />
          <Route path="/ligas"     element={<Ligas />} />
          <Route path="/equipos"   element={<Equipos />} />
          <Route path="/partidos"  element={<Partidos />} />
          <Route path="/jugadores" element={<Jugadores />} />
          <Route path="/live"             element={<Live />} />
          <Route path="/inconsistencias"  element={<Inconsistencias />} />
          <Route path="/drivers"          element={<Drivers />} />
        </Routes>
      </main>
    </div>
  )
}
