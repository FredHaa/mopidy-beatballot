export function duration(ms) {
  if (ms == null) return '–:––'
  const s = Math.max(0, Math.round(ms / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

export function artists(track) {
  return track?.artists?.join(', ') || 'Unknown artist'
}

/** A stable, pleasant colour for a user id. */
export function userColor(id) {
  let h = 0
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return `hsl(${h % 360} 75% 62%)`
}

export function initials(name) {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('')
}
