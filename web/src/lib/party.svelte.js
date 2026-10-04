// Connection to the Beat Ballot server and the shared reactive party state.

const BASE = import.meta.env.BASE_URL
const SESSION_KEY = 'beatballot.session'

function loadSession() {
  try {
    return JSON.parse(localStorage.getItem(SESSION_KEY))
  } catch {
    return null
  }
}

function saveSession(session) {
  try {
    if (session) localStorage.setItem(SESSION_KEY, JSON.stringify(session))
    else localStorage.removeItem(SESSION_KEY)
  } catch {
    // Private mode: the session just won't survive a reload.
  }
}

export const party = $state({
  session: loadSession(), // { token, user, pin }
  connected: false,
  state: null, // latest server snapshot
  receivedAt: 0, // performance.now() when `state` arrived
  pin: null, // guest PIN, sent to hosts so the big screen can show it
  toast: null,
})

// A ticking clock so countdowns and progress bars move between snapshots.
export const clock = $state({ now: performance.now() })
setInterval(() => (clock.now = performance.now()), 200)

/** Milliseconds since the snapshot, if the music is moving. */
function elapsed() {
  return party.state?.playback === 'playing' ? clock.now - party.receivedAt : 0
}

export function positionMs() {
  const now = party.state?.now
  if (!now) return 0
  const p = now.position_ms + elapsed()
  return now.end_ms != null ? Math.min(p, now.end_ms) : p
}

export function locksInMs() {
  const ms = party.state?.locks_in_ms
  return ms == null ? null : Math.max(0, ms - elapsed())
}

let toastTimer
export function toast(message, kind = 'error') {
  party.toast = { message, kind, id: Math.random() }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (party.toast = null), 3500)
}

let ws = null
let retries = 0
let reconnectTimer
let searchId = 0
const pendingSearches = new Map()

function socketUrl() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const token = encodeURIComponent(party.session.token)
  return `${proto}://${location.host}${BASE}ws?token=${token}`
}

export function connect() {
  if (!party.session || (ws && ws.readyState <= WebSocket.OPEN)) return
  clearTimeout(reconnectTimer)
  ws = new WebSocket(socketUrl())
  ws.onopen = () => {
    party.connected = true
    retries = 0
  }
  ws.onmessage = (event) => handle(JSON.parse(event.data))
  ws.onclose = (event) => {
    party.connected = false
    ws = null
    if (event.code === 4001) {
      leave()
      toast('Your session expired, please join again')
      return
    }
    reconnectTimer = setTimeout(connect, Math.min(1000 * 2 ** retries++, 8000))
  }
}

function handle(msg) {
  switch (msg.type) {
    case 'state':
      party.state = msg
      party.receivedAt = performance.now()
      break
    case 'hello':
      party.session = { ...party.session, user: msg.user }
      if (msg.pin) party.pin = msg.pin
      break
    case 'search_results':
      pendingSearches.get(msg.id)?.(msg.results)
      pendingSearches.delete(msg.id)
      break
    case 'error':
      toast(msg.message)
      break
  }
}

// Phones drop sockets while asleep; reconnect as soon as we're visible again.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && !ws) {
    retries = 0
    connect()
  }
})

export function send(msg) {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg))
    return true
  }
  toast('Reconnecting…')
  return false
}

export const vote = (uri) => send({ type: 'vote', uri })
export const retract = () => send({ type: 'retract' })
export const suggest = (uri) => send({ type: 'suggest', uri })
export const admin = (action, value) => send({ type: 'admin', action, value })

export function search(q) {
  return new Promise((resolve) => {
    const id = ++searchId
    pendingSearches.set(id, resolve)
    if (!send({ type: 'search', q, id })) resolve([])
  })
}

export async function join(pin, name) {
  const res = await fetch(`${BASE}api/join`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pin, name }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.error ?? 'Could not join')
  party.session = { token: data.token, user: data.user, pin: data.user.admin ? null : pin }
  saveSession(party.session)
  connect()
}

export function leave() {
  ws?.close()
  party.session = null
  party.state = null
  saveSession(null)
}

/** Backend logins waiting for the host (Tidal). Host only. */
export async function fetchLogins() {
  const token = encodeURIComponent(party.session?.token ?? '')
  const res = await fetch(`${BASE}api/logins?token=${token}`)
  return res.ok ? res.json() : {}
}

export async function fetchInfo() {
  const res = await fetch(`${BASE}api/info`)
  return res.json()
}
