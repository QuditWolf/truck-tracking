// App-wide reactive state: toasts.
export const toasts = $state({ list: [] })

let seq = 0
export function toast(text, kind = 'ok', ms = 3200) {
  const id = ++seq
  toasts.list.push({ id, text, kind })
  setTimeout(() => {
    toasts.list = toasts.list.filter((t) => t.id !== id)
  }, ms)
}
