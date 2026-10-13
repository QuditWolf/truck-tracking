<script>
  import Chips from './Chips.svelte'
  import { untrack } from 'svelte'
  import { api, localInput, line } from './api.js'

  // report = existing report when editing, null for a new one
  let { registry, report = null, onDone = () => {} } = $props()

  // Form is seeded once from props; the parent re-mounts it ({#key}) when the shift changes.
  const r0 = untrack(() => report)
  const shiftSite = untrack(() => registry.shift?.default_site || '')
  let trucks = $state(r0 ? [...r0.trucks] : [])
  let verb = $state(r0?.verb || '')
  let site = $state(r0 ? r0.site || '' : shiftSite)
  let remarks = $state(r0?.remarks || '')
  let advanced = $state(!!r0)
  let when = $state(r0 ? localInput(r0.event_time) : '')
  let warnings = $state([])
  let newEntries = $state([])
  let busy = $state(false)
  let error = $state('')

  // Editing: only send a time if the user actually changed it (keeps the original otherwise).
  const initialWhen = when
  const draft = $derived({
    trucks, verb, site: site || null, remarks,
    event_time: advanced && when && when !== initialWhen ? when : r0 ? r0.event_time : null,
  })
  const ready = $derived(trucks.length > 0 && verb)

  // Live check against everything already reported (duplicates, gaps, unshifted).
  let timer
  $effect(() => {
    const d = draft
    clearTimeout(timer)
    if (!ready) { warnings = []; newEntries = []; return }
    timer = setTimeout(async () => {
      try {
        const q = report ? `?report_id=${report.id}` : ''
        const r = await api.post(`/api/reports/check${q}`, d)
        warnings = r.warnings
        newEntries = r.new_entries
      } catch { /* check is advisory */ }
    }, 250)
  })

  async function submit() {
    busy = true
    error = ''
    try {
      const r = report ? await api.patch(`/api/reports/${report.id}`, draft) : await api.post('/api/reports', draft)
      if (!report) { trucks = []; remarks = ''; advanced = false; when = '' }
      onDone(r)
    } catch (e) {
      error = e.message
    } finally {
      busy = false
    }
  }
</script>

<form class="report" onsubmit={(e) => { e.preventDefault(); submit() }}>
  <Chips title="Truck" options={registry.truck} bind:value={trucks} multi placeholder="Truck" />
  <Chips title="Event" options={registry.verb} bind:value={verb} placeholder="Event" />
  <Chips title="Site" options={registry.site} bind:value={site} placeholder="Site" />

  <input class="remarks" bind:value={remarks} placeholder="Remarks (optional)" maxlength="200" />

  <details bind:open={advanced}>
    <summary>Advanced</summary>
    <label>Event time (IST)
      <input type="datetime-local" bind:value={when} max={localInput()} />
    </label>
    {#if !when}<p class="hint">Empty = now</p>{/if}
  </details>

  {#if ready}
    <p class="preview">{line({ ...draft, event_time: draft.event_time || new Date().toISOString() })}</p>
  {/if}
  {#each newEntries as n}<p class="note">{n} (will be added)</p>{/each}
  {#each warnings as w}<p class="warn">{w}</p>{/each}
  {#if error}<p class="error">{error}</p>{/if}

  <div class="actions">
    {#if report}<button type="button" class="ghost" onclick={() => onDone(null)}>Cancel</button>{/if}
    <button class="send" class:caution={warnings.length} disabled={!ready || busy}>
      {busy ? 'Sending…' : warnings.length ? (report ? 'Save anyway' : 'Send anyway') : report ? 'Save' : 'Send'}
    </button>
  </div>
</form>
