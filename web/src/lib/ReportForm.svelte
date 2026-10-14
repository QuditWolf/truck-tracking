<script>
  import { onDestroy, untrack } from 'svelte'
  import { slide } from 'svelte/transition'
  import Icon from './Icon.svelte'
  import Modal from './Modal.svelte'
  import Picker from './Picker.svelte'
  import { api, localInput, time } from './api.js'

  // report = existing report when editing; null composes a new one
  // tick: bumps when anyone changes data, so warnings are re-checked live
  let { registry, report = null, me = null, tick = 0, onDone = () => {} } = $props()

  // Seeded once from props; the parent re-mounts ({#key}) when the shift changes.
  const r0 = untrack(() => report)
  const shift = untrack(() => registry.shift)
  let trucks = $state(r0 ? [...r0.trucks] : [])
  let verb = $state(r0?.verb || '')
  let site = $state(r0 ? r0.site || '' : shift?.default_site || '')
  let remarks = $state(r0?.remarks || '')
  let advanced = $state(false)
  let when = $state(r0 ? localInput(r0.event_time) : '')
  const initialWhen = untrack(() => when)

  let warnings = $state([])
  let newEntries = $state([])
  let busy = $state(false)
  let error = $state('')
  let askShift = $state(false)

  const draft = $derived({
    trucks, verb, site: site || null, remarks,
    event_time: when && when !== initialWhen ? when : r0 ? r0.event_time : null,
  })
  const ready = $derived(trucks.length > 0 && !!verb)
  const shownTime = $derived(draft.event_time ? time(draft.event_time) : time(new Date().toISOString()))

  // Warnings are re-checked whenever the draft changes, whenever anyone changes data (tick, pushed
  // live), and every 15 s as a fallback in case the live connection is down.
  let poll = $state(0)
  let now = $state(Date.now())
  const timers = [setInterval(() => poll++, 15000), setInterval(() => (now = Date.now()), 20000)]
  onDestroy(() => timers.forEach(clearInterval))

  let timer
  let seq = 0
  $effect(() => {
    const d = draft
    tick; poll
    clearTimeout(timer)
    if (!ready) { warnings = []; newEntries = []; return }
    timer = setTimeout(async () => {
      const mine = ++seq
      try {
        const r = await api.post(`/api/reports/check${r0 ? `?report_id=${r0.id}` : ''}`, d)
        if (mine !== seq) return // a newer check is on its way
        // with no shift running the confirm dialog covers this
        warnings = r.details.filter((w) => !(w.code === 'unshifted' && !r0 && !shift))
        newEntries = r.new_entries
        now = Date.now()
      } catch { /* advisory only */ }
    }, 220)
  })

  function ago(iso) {
    const min = Math.floor((now - new Date(iso).getTime()) / 60000)  // times are whole minutes: floor, not round
    if (min < 1) return 'just now'
    if (min < 60) return `${min} min ago`
    return `${Math.floor(min / 60)}h ${min % 60}m ago`
  }
  const sayWarning = (w) => w.code === 'duplicate' && w.ref
    ? `${w.truck} ${w.ref.verb}${w.ref.site ? ' ' + w.ref.site : ''} reported ${ago(w.ref.time)} by ${w.ref.user} (@${time(w.ref.time)})`
    : w.text
  const duplicate = $derived(warnings.some((w) => w.code === 'duplicate'))

  function submit() {
    if (!r0 && !shift) askShift = true
    else send(false)
  }

  async function send(startShift) {
    askShift = false
    busy = true
    error = ''
    try {
      const body = { ...draft, ...(startShift ? { start_shift: true } : {}) }
      const r = r0 ? await api.patch(`/api/reports/${r0.id}`, body) : await api.post('/api/reports', body)
      if (!r0) { trucks = []; remarks = ''; when = ''; advanced = false }
      onDone(r, startShift)
    } catch (e) {
      error = e.message
    } finally {
      busy = false
    }
  }
</script>

<form class="composer" class:editing={!!r0} onsubmit={(e) => { e.preventDefault(); submit() }}>
  <div class="fields">
    <Picker label="Truck" options={registry.truck} bind:value={trucks} multi />
    <Picker label="Event" options={registry.verb} bind:value={verb} variant="labelled" />
    <Picker label="Site" options={registry.site} bind:value={site} variant="labelled" />

    <div class="extras">
      <input class="input" bind:value={remarks} placeholder="Remarks — optional" maxlength="200" />
      {#if !advanced && !r0}
        <button type="button" class="btn quiet when" title="Set a different event time"
                onclick={() => { advanced = true; when = when || localInput() }}>
          <Icon name="clock" size={16} /> Now
        </button>
      {/if}
    </div>
    {#if advanced || r0}
      <div class="when-row" transition:slide={{ duration: 180 }}>
        <label class="field grow">
          <span>Event time · IST</span>
          <input class="input" type="datetime-local" bind:value={when} max={localInput()} />
        </label>
        {#if !r0}
          <button type="button" class="btn ghost" onclick={() => { advanced = false; when = '' }}>Use now</button>
        {/if}
      </div>
    {/if}
  </div>

  <div class="dock">
    <div class="ticket" class:ready>
      {#if ready}
        <span>{trucks.join(',')}</span>
        <span class="t-verb">{verb}</span>
        {#if site}<span>{site}</span>{/if}
        <span class="t-dim">@{shownTime}</span>
        {#if me}<span class="t-user">~{me.name.split(' ')[0]}</span>{/if}
      {:else}
        <span class="t-hint">Pick a truck and an event</span>
      {/if}
    </div>
    {#each newEntries as n (n)}<p class="notice info" transition:slide={{ duration: 160 }}>{n} — will be added to the list</p>{/each}
    {#each warnings as w (w.text)}<p class="notice" transition:slide={{ duration: 160 }}><Icon name="warn" size={15} />{sayWarning(w)}</p>{/each}
    {#if error}<p class="notice err">{error}</p>{/if}
    <div class="dock-actions">
      {#if r0}<button type="button" class="btn quiet" onclick={() => onDone(null)}>Cancel</button>{/if}
      <button class="btn send" class:signal={!warnings.length} class:caution={warnings.length > 0} disabled={!ready || busy}>
        {busy ? 'Sending…' : warnings.length ? (r0 ? 'Save anyway' : duplicate ? 'Report again' : 'Send anyway') : r0 ? 'Save changes' : 'Send report'}
        {#if !busy}<Icon name="send" size={18} />{/if}
      </button>
    </div>
  </div>
</form>

<Modal bind:open={askShift} title="No shift is running">
  <p>Start a shift with this report so it's counted in the summaries?</p>
  <p class="mute">Shift starts {draft.event_time ? `at ${time(draft.event_time)}` : 'now'}{site ? ` · default site ${site}` : ''}.</p>
  {#snippet actions()}
    <button class="btn ghost" onclick={() => (askShift = false)}>Cancel</button>
    <button class="btn quiet" onclick={() => send(false)}>Send without shift</button>
    <button class="btn signal" onclick={() => send(true)}>Start shift &amp; send</button>
  {/snippet}
</Modal>

<style>
  .composer { display: flex; flex-direction: column; min-height: 100%; }
  .fields { display: flex; flex-direction: column; gap: 22px; padding-bottom: 20px; flex: 1; }
  .extras { display: flex; gap: 8px; }
  .extras .input { flex: 1; }
  .when { height: 44px; }
  .when-row { display: flex; align-items: flex-end; gap: 8px; }
  .when-row .btn { height: 44px; }

  .dock {
    position: sticky; bottom: 0; z-index: 2; margin: 0 calc(-1 * var(--pad)); padding: 16px var(--pad) var(--pad);
    display: flex; flex-direction: column; gap: 8px;
    background: linear-gradient(to bottom, transparent, var(--paper) 20px);
  }
  .editing .dock { margin: 0; padding: 14px 0 0; background: none; position: static; }

  .ticket {
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap; min-height: 50px; padding: 10px 14px;
    border-radius: var(--r); background: var(--surface); box-shadow: inset 0 0 0 1px var(--hair);
    font: 600 15px/1.2 var(--mono); letter-spacing: -0.03em; transition: box-shadow .25s var(--ease);
  }
  .ticket.ready { box-shadow: inset 0 0 0 1.5px var(--ink), var(--shadow); }
  .t-verb { color: var(--signal); }
  .t-dim { color: var(--mute); font-weight: 500; }
  .t-user { margin-left: auto; color: var(--mute); font: 500 13.5px var(--sans); }
  .t-hint { color: var(--mute); font: 500 13.5px var(--sans); }

  .dock-actions { display: flex; gap: 8px; }
  .send { flex: 1; height: 54px; font-size: 16px; border-radius: 12px; }
</style>
