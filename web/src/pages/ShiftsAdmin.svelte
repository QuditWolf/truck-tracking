<script>
  // Admin: every shift with its counts; edit times/site, add or subtract counts, delete / restore.
  // Nothing is removed from the database — deletes are marks and can be restored.
  import Icon from '../lib/Icon.svelte'
  import Modal from '../lib/Modal.svelte'
  import Picker from '../lib/Picker.svelte'
  import { api, dateTime, halves, localInput } from '../lib/api.js'
  import { toast } from '../lib/stores.svelte.js'

  let { registry, onChange } = $props()

  let shifts = $state([])
  let showDeleted = $state(false)
  async function load() { shifts = await api.get(`/api/admin/shifts?include_deleted=${showDeleted}`) }
  $effect(() => { showDeleted; load() })

  async function run(fn, msg) {
    try { await fn(); toast(msg); await load(); onChange?.() } catch (e) { toast(e.message, 'warn') }
  }

  // edit times / default site
  let edit = $state(null)
  let editOpen = $state(false)
  function openEdit(s) {
    edit = { id: s.id, started_at: localInput(s.started_at), ended_at: s.ended_at ? localInput(s.ended_at) : '', sites: [...(s.sites || [])] }
    editOpen = true
  }
  async function saveEdit() {
    editOpen = false
    await run(() => api.patch(`/api/shifts/${edit.id}`, { started_at: edit.started_at, ended_at: edit.ended_at, sites: edit.sites }), 'Shift updated')
  }

  // add / subtract counts
  let adj = $state(null)
  let adjOpen = $state(false)
  function openAdj(s, negative) {
    adj = { shift: s, negative, kind: 'load', count: 1, trucks: [], site: '', note: '', half: false, quiet: true }
    adjOpen = true
  }
  async function saveAdj() {
    adjOpen = false
    const a = adj
    await run(() => api.post('/api/manual', { shift_id: a.shift.id, trucks: a.trucks, kind: a.kind, count: a.count, site: a.site || null,
                                              note: a.note, half: a.half, negative: a.negative, post_fleet: !a.quiet }),
              `${a.negative ? '−' : '+'}${a.count} ${a.kind}${a.count > 1 ? 's' : ''} recorded`)
  }
  const removeEntry = (m) => run(() => api.del(`/api/manual/${m.id}`), 'Entry removed')
  const restoreEntry = (m) => run(() => api.post(`/api/manual/${m.id}/restore`), 'Entry restored')

  const del = (s) => confirm(`Delete the shift ${s.title}? Its reports stay; it can be restored.`) &&
    run(() => api.patch(`/api/shifts/${s.id}`, { deleted: true }), 'Shift deleted')
  const restore = (s) => run(() => api.patch(`/api/shifts/${s.id}`, { deleted: false }), 'Shift restored')
  const reopen = (s) => run(() => api.patch(`/api/shifts/${s.id}`, { ended_at: '' }), 'Shift reopened')

  // record a past shift that wasn't tracked in detail: times, sites, and totals (unnamed or per truck)
  let rec = $state(null)
  let recOpen = $state(false)
  function openRec() {
    rec = { started_at: '', ended_at: '', sites: [], loads: 0, loadSite: '', unloads: 0, unloadSite: '', trucks: [], note: '', quiet: true }
    recOpen = true
  }
  async function saveRec() {
    const r = rec
    try {
      const sh = await api.post('/api/admin/shifts', { started_at: r.started_at, ended_at: r.ended_at, sites: r.sites })
      const add = (kind, count, site) => count > 0 && api.post('/api/manual', {
        shift_id: sh.id, trucks: r.trucks, kind, count, site: site || null, note: r.note || 'recorded later', post_fleet: !r.quiet })
      await add('load', r.loads, r.loadSite)
      await add('unload', r.unloads, r.unloadSite)
      recOpen = false
      toast('Shift recorded')
      await load()
      onChange?.()
    } catch (e) { toast(e.message, 'warn') }
  }

  const siteFits = (kind) => registry.site.filter((x) => (kind === 'load' ? x.site_type !== 'unloading' : x.site_type !== 'loading'))
</script>

<div class="shifts">
  <div class="bar">
    <label class="check"><input type="checkbox" bind:checked={showDeleted} /> Show deleted shifts</label>
    <button class="btn signal sm" onclick={openRec}><Icon name="plus" size={14} />New shift</button>
  </div>

  {#each shifts as s (s.id)}
    <section class="card shift" class:deleted={s.deleted}>
      <div class="card-h">
        <div class="t">
          <h3>{s.title || dateTime(s.started_at)}</h3>
          <span class="mute small">
            started {dateTime(s.started_at)}{s.started_by ? ` by ${s.started_by}` : ''}
            {#if s.ended_at} · ended {dateTime(s.ended_at)}{s.ended_by ? ` by ${s.ended_by}` : ''}{/if}
            {#if s.sites?.length} · sites {s.sites.join(', ')}{/if}
          </span>
        </div>
        {#if s.deleted}<span class="pill warn">deleted</span>{:else if s.open}<span class="pill live">running</span>{/if}
      </div>
      <div class="card-b">
        <div class="nums">
          <div><b class="mono">{s.loaded}</b><span>loaded{s.loaded_abs !== s.loaded ? ` · ${halves(s.loaded_abs)} loads` : ''}{s.loaded_with_unlogged > s.loaded ? ` · ${s.loaded_with_unlogged} incl. unlogged` : ''}</span></div>
          <div><b class="mono">{s.unloaded}</b><span>unloaded{s.unloaded_abs !== s.unloaded ? ` · ${halves(s.unloaded_abs)} loads` : ''}</span></div>
        </div>
        {#if s.manual.length}
          <ul class="entries">
            {#each s.manual as m (m.id)}
              <li class:neg={m.negative}>
                <span class="mono">{m.negative ? '−' : '+'}{m.count} {m.kind}{m.count > 1 ? 's' : ''} {m.truck || 'shift total'}{m.site ? ` ${m.site}` : ''}{m.half ? ' ½' : ''}</span>
                <span class="mute small">{m.note}{m.note ? ' · ' : ''}{m.user}</span>
                <button class="btn ghost sm icon danger" title="Remove" onclick={() => removeEntry(m)}><Icon name="trash" size={13} /></button>
              </li>
            {/each}
          </ul>
        {/if}
        <div class="row">
          {#if s.deleted}
            <button class="btn quiet sm" onclick={() => restore(s)}>Restore shift</button>
          {:else}
            <a class="btn quiet sm" href="#summary/{s.id}">Summary</a>
            <button class="btn quiet sm" onclick={() => openAdj(s, false)}>+ Add</button>
            <button class="btn quiet sm" onclick={() => openAdj(s, true)}>− Subtract</button>
            <button class="btn quiet sm" onclick={() => openEdit(s)}><Icon name="edit" size={13} />Edit</button>
            {#if !s.open}<button class="btn ghost sm" onclick={() => reopen(s)}>Reopen</button>{/if}
            <span class="grow"></span>
            <button class="btn ghost sm danger" onclick={() => del(s)}>Delete shift</button>
          {/if}
        </div>
      </div>
    </section>
  {:else}
    <div class="empty-state"><p>No shifts.</p></div>
  {/each}
</div>

<Modal bind:open={recOpen} title="Record a past shift">
  {#if rec}
    <p class="mute small">For a shift that happened without detailed tracking.</p>
    <div class="two">
      <label class="field"><span>Started · IST</span><input class="input" type="datetime-local" bind:value={rec.started_at} /></label>
      <label class="field"><span>Ended · IST</span><input class="input" type="datetime-local" bind:value={rec.ended_at} /></label>
    </div>
    <Picker label="Sites" options={registry.site} bind:value={rec.sites} multi variant="labelled" />
    <div class="two">
      <label class="field"><span>Loads</span><input class="input mono" type="number" min="0" max="50" bind:value={rec.loads} /></label>
      <label class="field"><span>at loading site</span>
        <select class="select" bind:value={rec.loadSite}><option value="">—</option>
          {#each siteFits('load') as x}<option value={x.code}>{x.code}</option>{/each}</select></label>
      <label class="field"><span>Unloads</span><input class="input mono" type="number" min="0" max="50" bind:value={rec.unloads} /></label>
      <label class="field"><span>at unloading site</span>
        <select class="select" bind:value={rec.unloadSite}><option value="">—</option>
          {#each siteFits('unload') as x}<option value={x.code}>{x.code}</option>{/each}</select></label>
    </div>
    <Picker label="Trucks (empty = unknown trolley)" options={registry.truck} bind:value={rec.trucks} multi placeholder="Truck / reg. no." />
    {#if rec.trucks.length > 1}<p class="mute small">Each selected truck gets these counts.</p>{/if}
    <input class="input" bind:value={rec.note} placeholder="Note (e.g. from the paper register)" maxlength="120" />
    <label class="check"><input type="checkbox" bind:checked={rec.quiet} /> Don't send to fleet group</label>
    <p class="mute small">The control group is told about the counts. More can be added afterwards with + Add.</p>
  {/if}
  {#snippet actions()}
    <button class="btn ghost" onclick={() => (recOpen = false)}>Cancel</button>
    <button class="btn signal" disabled={!rec?.started_at || !rec?.ended_at} onclick={saveRec}>Record shift</button>
  {/snippet}
</Modal>

<Modal bind:open={editOpen} title="Edit shift">
  {#if edit}
    <label class="field"><span>Started · IST</span><input class="input" type="datetime-local" bind:value={edit.started_at} /></label>
    <label class="field"><span>Ended · IST <small class="mute">(empty = still running)</small></span><input class="input" type="datetime-local" bind:value={edit.ended_at} /></label>
    <Picker label="Shift sites (first = default)" options={registry.site} bind:value={edit.sites} multi variant="labelled" />
    <p class="mute small">Reports move in or out of the shift by their time.</p>
  {/if}
  {#snippet actions()}
    <button class="btn ghost" onclick={() => (editOpen = false)}>Cancel</button>
    <button class="btn signal" onclick={saveEdit}>Save</button>
  {/snippet}
</Modal>

<Modal bind:open={adjOpen} title={adj ? `${adj.negative ? 'Subtract from' : 'Add to'} ${adj.shift.title}` : ''}>
  {#if adj}
    <div class="row2">
      <div class="seg">
        <button type="button" class:on={adj.kind === 'load'} onclick={() => (adj.kind = 'load')}>Loads</button>
        <button type="button" class:on={adj.kind === 'unload'} onclick={() => (adj.kind = 'unload')}>Unloads</button>
      </div>
      <div class="stepper">
        <button type="button" class="btn quiet sm icon" onclick={() => (adj.count = Math.max(1, adj.count - 1))}>−</button>
        <span class="mono">{adj.negative ? '−' : '+'}{adj.count}</span>
        <button type="button" class="btn quiet sm icon" onclick={() => (adj.count = Math.min(50, adj.count + 1))}>+</button>
      </div>
    </div>
    <Picker label={adj.negative ? 'Trucks (optional — empty = shift total)' : 'Trucks'} options={registry.truck} bind:value={adj.trucks} multi placeholder="Truck / reg. no." />
    {#if !adj.negative}<div><button type="button" class="btn quiet sm" onclick={() => (adj.trucks = [...new Set([...adj.trucks, 'UNKNOWN'])])}>+ Unknown trolley</button></div>{/if}
    <Picker label="Site (optional)" options={siteFits(adj.kind)} bind:value={adj.site} variant="labelled" />
    <input class="input" bind:value={adj.note} placeholder="Reason / note" maxlength="120" />
    {#if !adj.negative}<label class="check"><input type="checkbox" bind:checked={adj.half} /> Half load</label>{/if}
    <label class="check"><input type="checkbox" bind:checked={adj.quiet} /> Don't send to fleet group</label>
    <p class="mute small">The control group is always told. Removable any time.</p>
  {/if}
  {#snippet actions()}
    <button class="btn ghost" onclick={() => (adjOpen = false)}>Cancel</button>
    <button class="btn signal" disabled={!adj || (!adj.negative && !adj.trucks.length)} onclick={saveAdj}>{adj?.negative ? 'Subtract' : 'Add'}</button>
  {/snippet}
</Modal>

<style>
  .shifts { display: flex; flex-direction: column; gap: 12px; max-width: 900px; }
  .shift.deleted { opacity: .6; }
  .bar { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; }
  .two { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 10px; }
  .two :global(.input), .two :global(.select) { min-width: 0; }
  @media (max-width: 480px) { .two { grid-template-columns: minmax(0, 1fr); } }
  .t { display: flex; flex-direction: column; gap: 3px; }
  .small { font-size: 12.5px; }
  .nums { display: flex; gap: 28px; margin-bottom: 10px; }
  .nums div { display: flex; flex-direction: column; }
  .nums b { font-size: 26px; font-weight: 600; letter-spacing: -0.05em; line-height: 1.1; }
  .nums span { font-size: 12.5px; color: var(--mute); }
  .entries { list-style: none; margin: 0 0 10px; padding: 0; border-top: 1px solid var(--hair-2); }
  .entries li { display: grid; grid-template-columns: auto 1fr auto; gap: 10px; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--hair-2); font-size: 13px; }
  .entries li.neg .mono { color: var(--red); }
  .row { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  .row2 { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; }
  .stepper { display: flex; align-items: center; gap: 10px; }
  .stepper .mono { font-size: 18px; font-weight: 600; min-width: 34px; text-align: center; }
  @media (max-width: 520px) { .entries li { grid-template-columns: 1fr auto; } .entries li .mute { grid-column: 1; } }
</style>
