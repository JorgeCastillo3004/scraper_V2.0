const STYLES = {
  running:  'bg-green-500/20 text-green-400 border-green-500/40',
  paused:   'bg-yellow-500/20 text-yellow-400 border-yellow-500/40',
  stopped:  'bg-gray-500/20  text-gray-400  border-gray-500/40',
}
const DOTS = {
  running: '● ',
  paused:  '⏸ ',
  stopped: '○ ',
}

export default function StatusBadge({ status = 'stopped' }) {
  const style = STYLES[status] ?? STYLES.stopped
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${style}`}>
      {DOTS[status] ?? ''}{status.toUpperCase()}
    </span>
  )
}
