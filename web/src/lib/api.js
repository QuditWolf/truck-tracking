// Thin fetch wrapper. Cookies carry the session.
async function call(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
    credentials: 'same-origin',
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const err = new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${res.status}`)
    err.status = res.status
    throw err
  }
  return data
}

export const api = {
  get: (p) => call('GET', p),
  post: (p, b = {}) => call('POST', p, b),
  put: (p, b) => call('PUT', p, b),
  patch: (p, b) => call('PATCH', p, b),
  del: (p) => call('DELETE', p),
}

// All times are IST.
const fmt = (opts) => new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', hour12: false, ...opts })
const hm = fmt({ hour: '2-digit', minute: '2-digit' })
const dhm = fmt({ day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })

// Naive strings (from datetime-local inputs) are IST.
const parse = (iso) => new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + '+05:30')
export const time = (iso) => (iso ? hm.format(parse(iso)) : '')
export const dateTime = (iso) => (iso ? dhm.format(parse(iso)) : '')

// "YYYY-MM-DDTHH:mm" in IST, for <input type="datetime-local">. Backend reads naive times as IST.
export function localInput(iso) {
  const d = iso ? parse(iso) : new Date()
  const p = Object.fromEntries(
    fmt({ year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
      .formatToParts(d)
      .map((x) => [x.type, x.value]),
  )
  return `${p.year}-${p.month}-${p.day}T${p.hour === '24' ? '00' : p.hour}:${p.minute}`
}

export const todayIST = () => localInput().slice(0, 10)

export const line = (r) => [r.trucks.join(','), r.verb, r.site, '@' + time(r.event_time)].filter(Boolean).join(' ')
