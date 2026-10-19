// Music service logins (Tidal, SoundCloud): for the hub owner, or the host of
// a standalone party.

const BASE = import.meta.env.BASE_URL

async function api(token, method, path, body) {
  const res = await fetch(`${BASE}api/services${path}`, {
    method,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token ?? ''}` },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw Object.assign(new Error(data.error ?? `Request failed (${res.status})`), { status: res.status })
  return data
}

export const getServices = (token) => api(token, 'GET', '')
export const serviceAction = (token, service, action, body = {}) =>
  api(token, 'POST', `/${service}/${action}`, body)
