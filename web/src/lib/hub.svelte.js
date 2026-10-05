// The hub owner's API: parties, pairing players, the Tidal login.

const BASE = import.meta.env.BASE_URL
const OWNER_KEY = 'beatballot.owner'

function load() {
  try {
    return localStorage.getItem(OWNER_KEY)
  } catch {
    return null
  }
}

export const owner = $state({ token: load() })

async function api(method, path, body) {
  const res = await fetch(`${BASE}api/${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(owner.token ? { Authorization: `Bearer ${owner.token}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  if (res.status === 401) logout()
  if (!res.ok) throw new Error(data.error ?? `Request failed (${res.status})`)
  return data
}

export async function login(pin) {
  const { token } = await api('POST', 'hub/login', { pin })
  owner.token = token
  try {
    localStorage.setItem(OWNER_KEY, token)
  } catch {
    // Private mode: log in again next time.
  }
}

export function logout() {
  owner.token = null
  try {
    localStorage.removeItem(OWNER_KEY)
  } catch {
    // ignore
  }
}

export const listRooms = () => api('GET', 'hub/rooms').then((d) => d.rooms)
export const createRoom = (fields) => api('POST', 'hub/rooms', fields).then((d) => d.room)
export const updateRoom = (id, changes) => api('PATCH', `hub/rooms/${id}`, changes).then((d) => d.room)
export const deleteRoom = (id) => api('DELETE', `hub/rooms/${id}`)
export const pairPlayer = (id) => api('POST', `hub/rooms/${id}/pair`, {})
export const unpairPlayer = (id) => api('POST', `hub/rooms/${id}/unpair`, {})

export async function tidalLogin() {
  const res = await fetch(`${BASE}api/logins?token=${encodeURIComponent(owner.token ?? '')}`)
  return res.ok ? (await res.json()).tidal : null
}
