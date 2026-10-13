<script>
  import Icon from '../lib/Icon.svelte'
  import Modal from '../lib/Modal.svelte'
  import { api, dateTime, localInput } from '../lib/api.js'
  import { toast } from '../lib/stores.svelte.js'

  let { onChange } = $props()

  let tab = $state('registry')
  let kind = $state('truck')
  let items = $state([])
  let users = $state([])
  let settings = $state({})
  let shifts = $state([])
  let audit = $state([])
  let error = $state('')

  async function load() {
    try {
      if (tab === 'registry') items = await api.get('/api/admin/registry')
      if (tab === 'users') users = await api.get('/api/admin/users')
      if (tab === 'settings') settings = await api.get('/api/admin/settings')
      if (tab === 'shifts') shifts = await api.get('/api/shifts?limit=200')
      if (tab === 'audit') audit = await api.get('/api/admin/audit?limit=300')
    } catch (e) { toast(e.message, 'warn') }
  }
  $effect(() => { tab; load() })

  async function run(fn, msg) {
    error = ''
    try {
      await fn()
      if (msg) toast(msg)
      await load()
      onChange()
      return true
    } catch (e) {
      error = e.message
      return false
    }
  }

  // ── registry ──
  const canon = $derived(items.filter((i) => i.kind === kind && !i.merged_into))
  const aliasesOf = (id) => items.filter((i) => i.merged_into === id)
  const counts = $derived(Object.fromEntries(['truck', 'site', 'verb'].map((k) => [k, items.filter((i) => i.kind === k && !i.merged_into && i.active).length])))

  let form = $state(null) // { id?, code, label, site_type, plate, notes, active }
  let formOpen = $state(false)
  let newAlias = $state('')
  let mergeInto = $state('')

  function openNew() {
    form = { code: '', label: '', site_type: '', plate: '', notes: '' }
    error = ''
    formOpen = true
  }
  function openEdit(i) {
    form = { ...i, site_type: i.site_type || '' }
    error = ''; newAlias = ''; mergeInto = ''
    formOpen = true
  }
  async function save() {
    const body = { code: form.code.trim(), label: form.label.trim() || form.code.trim(), plate: form.plate, notes: form.notes,
                   site_type: kind === 'site' ? form.site_type || null : null }
    const ok = form.id
      ? await run(() => api.patch(`/api/admin/registry/${form.id}`, body), `${body.code} saved`)
      : await run(() => api.post('/api/admin/registry', { kind, ...body }), `${body.code} added`)
    if (ok) formOpen = false
  }
  const addAlias = () => newAlias.trim() && run(() => api.post(`/api/admin/registry/${form.id}/alias`, { code: newAlias.trim() }), `Alias ${newAlias} added`).then(() => (newAlias = ''))
  const unmerge = (a) => run(() => api.post(`/api/admin/registry/${a.id}/unmerge`), `${a.code} is separate again`)
  const delAlias = (a) => run(async () => { const r = await api.del(`/api/admin/registry/${a.id}`); if (r.result === 'deactivated') toast(`${a.code} is in use — kept as inactive`, 'warn') })
  async function merge() {
    if (!mergeInto) return
    const target = items.find((x) => x.id === +mergeInto)
    if (await run(() => api.post(`/api/admin/registry/${form.id}/merge`, { into: +mergeInto }), `${form.code} merged into ${target.code}`)) formOpen = false
  }
  async function del() {
    let res
    if (await run(async () => { res = await api.del(`/api/admin/registry/${form.id}`) })) {
      toast(res.result === 'deactivated' ? `${form.code} is in use — deactivated` : `${form.code} deleted`)
      formOpen = false
    }
  }
  const reactivate = () => run(() => api.patch(`/api/admin/registry/${form.id}`, { active: true }), `${form.code} active`).then(() => (formOpen = false))
  const setType = (i, t) => run(() => api.patch(`/api/admin/registry/${i.id}`, { site_type: t || null }), `${i.code}: ${t || 'no type'}`)

  // ── shifts ──
  let shiftForm = $state(null)
  let shiftOpen = $state(false)
  function openShift(s) {
    shiftForm = { id: s.id, started_at: localInput(s.started_at), ended_at: s.ended_at ? localInput(s.ended_at) : '' }
    error = ''
    shiftOpen = true
  }
  async function saveShift() {
    if (await run(() => api.patch(`/api/shifts/${shiftForm.id}`, { started_at: shiftForm.started_at, ended_at: shiftForm.ended_at }), 'Shift updated')) shiftOpen = false
  }
  async function deleteShift() {
    if (await run(() => api.patch(`/api/shifts/${shiftForm.id}`, { deleted: true }), 'Shift deleted')) shiftOpen = false
  }
  const dur = (s) => {
    const ms = (s.ended_at ? new Date(s.ended_at) : new Date()) - new Date(s.started_at)
    return `${Math.floor(ms / 3.6e6)}h ${String(Math.floor((ms % 3.6e6) / 6e4)).padStart(2, '0')}m`
  }

  const parse = (j) => { try { return j ? JSON.parse(j) : null } catch { return j } }
</script>

<div class="admin">
  <div class="toolbar">
    <div class="seg">
      {#each ['registry', 'shifts', 'users', 'settings', 'audit'] as t}
        <button class:on={tab === t} onclick={() => (tab = t)}>{t}</button>
      {/each}
    </div>
  </div>

  {#if tab === 'registry'}
    <div class="toolbar">
      <div class="seg">
        {#each [['truck', 'Trucks'], ['site', 'Sites'], ['verb', 'Events']] as [k, label]}
          <button class:on={kind === k} onclick={() => (kind = k)}>{label} <span class="count mono">{counts[k] ?? ''}</span></button>
        {/each}
      </div>
      <span class="grow"></span>
      <button class="btn signal sm" onclick={openNew}><Icon name="plus" size={15} />Add {kind === 'verb' ? 'event' : kind}</button>
    </div>

    <div class="card">
      <div class="table-wrap">
        <table class="table clickable">
          <thead>
            <tr>
              <th>Code</th><th>Name</th>
              {#if kind === 'truck'}<th>Licence no.</th>{/if}
              {#if kind === 'site'}<th>Type</th>{/if}
              {#if kind !== 'verb'}<th>Aliases</th>{/if}
              <th>Remarks</th><th></th>
            </tr>
          </thead>
          <tbody class="stagger">
            {#each canon as i (i.id)}
              <tr class:inactive={!i.active} onclick={() => openEdit(i)}>
                <td class="mono strong">{i.code}</td>
                <td>{i.label !== i.code ? i.label : ''}</td>
                {#if kind === 'truck'}<td class="mono plate">{i.plate || ''}</td>{/if}
                {#if kind === 'site'}
                  <td onclick={(e) => e.stopPropagation()}>
                    <select class="select sm type" class:missing={!i.site_type} value={i.site_type || ''} onchange={(e) => setType(i, e.target.value)}>
                      <option value="">Set type…</option><option>loading</option><option>unloading</option><option>depot</option>
                    </select>
                  </td>
                {/if}
                {#if kind !== 'verb'}
                  <td>{#each aliasesOf(i.id) as a}<span class="tag mono" class:inactive={!a.active}>{a.code}</span>{/each}</td>
                {/if}
                <td class="notes">{i.notes || ''}</td>
                <td class="num">{#if !i.active}<span class="pill idle plain">inactive</span>{/if}<Icon name="chevron" size={15} /></td>
              </tr>
            {:else}
              <tr><td colspan="7" class="mute">Nothing here yet.</td></tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>

  {:else if tab === 'shifts'}
    <div class="card">
      <div class="table-wrap">
        <table class="table clickable">
          <thead><tr><th>Started</th><th>Ended</th><th class="num">Length</th><th>Default site</th><th></th></tr></thead>
          <tbody>
            {#each shifts as s (s.id)}
              <tr onclick={() => openShift(s)}>
                <td class="mono">{dateTime(s.started_at)}</td>
                <td class="mono">{#if s.ended_at}{dateTime(s.ended_at)}{:else}<span class="pill live">running</span>{/if}</td>
                <td class="num">{dur(s)}</td>
                <td class="mono">{s.default_site || ''}</td>
                <td class="num"><Icon name="chevron" size={15} /></td>
              </tr>
            {:else}
              <tr><td colspan="5" class="mute">No shifts yet.</td></tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>

  {:else if tab === 'users'}
    <div class="card">
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>Name</th><th>Phone</th><th>Email</th><th class="num">Reports</th><th>Joined</th><th></th></tr></thead>
          <tbody>
            {#each users as u (u.id)}
              <tr class:inactive={u.disabled}>
                <td class="strong">{u.name || '—'} {#if u.is_admin}<span class="pill plain">admin</span>{/if}</td>
                <td class="mono">{u.phone || ''}</td>
                <td>{u.email}</td>
                <td class="num">{u.reports}</td>
                <td class="mono small">{dateTime(u.created_at)}</td>
                <td class="num">
                  {#if !u.is_admin}
                    <button class="btn quiet sm" class:danger={!u.disabled}
                      onclick={() => run(() => api.patch(`/api/admin/users/${u.id}`, { disabled: !u.disabled }), u.disabled ? `${u.name} enabled` : `${u.name} disabled`)}>
                      {u.disabled ? 'Enable' : 'Disable'}
                    </button>
                  {/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>

  {:else if tab === 'settings'}
    <form class="card settings" onsubmit={(e) => { e.preventDefault(); run(() => api.put('/api/admin/settings', settings), 'Settings saved') }}>
      <div class="card-h"><h3>WhatsApp</h3></div>
      <div class="card-b stack">
        <fieldset class="modes">
          <legend class="field-label">Fleet group mode</legend>
          {#each [['silent', 'Silent', 'Fleet group only receives relayed reports. Confirmations, questions and summaries go to the control group.'],
                  ['full', 'Full', 'Confirmations and summaries are also posted in the fleet group.']] as [v, t, d]}
            <label class="mode" class:on={settings.fleet_mode === v}>
              <input type="radio" bind:group={settings.fleet_mode} value={v} />
              <b>{t}</b><span>{d}</span>
            </label>
          {/each}
        </fieldset>
        <div class="two">
          <label class="field"><span>Summary every (minutes, 0 = off)</span><input class="input" type="number" min="0" bind:value={settings.summary_interval_min} /></label>
          <label class="field"><span>Warn when a shift runs longer than (hours)</span><input class="input" type="number" min="1" bind:value={settings.shift_stale_hours} /></label>
        </div>
        {#if error}<p class="notice err">{error}</p>{/if}
        <div><button class="btn signal">Save settings</button></div>
      </div>
    </form>

  {:else}
    <div class="card">
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>When</th><th>Action</th><th>Change</th></tr></thead>
          <tbody>
            {#each audit as a (a.id)}
              <tr>
                <td class="mono small nowrap">{dateTime(a.at)}</td>
                <td class="nowrap"><span class="pill plain">{a.action}</span> <span class="mute">{a.entity} {a.entity_id ?? ''}</span></td>
                <td>
                  <details>
                    <summary class="mute small">details</summary>
                    <div class="diff">
                      {#if a.before}<pre class="mono before">{JSON.stringify(parse(a.before), null, 1)}</pre>{/if}
                      {#if a.after}<pre class="mono after">{JSON.stringify(parse(a.after), null, 1)}</pre>{/if}
                    </div>
                  </details>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {/if}
</div>

<Modal bind:open={formOpen} title={form?.id ? `Edit ${form.code}` : `Add ${kind === 'verb' ? 'event' : kind}`}>
  {#if form}
    <form class="stack" id="regform" onsubmit={(e) => { e.preventDefault(); save() }}>
      <div class="two">
        <label class="field"><span>Code</span><input class="input mono" bind:value={form.code} required placeholder={kind === 'truck' ? 'A' : 'SOC'} /></label>
        <label class="field"><span>Name</span><input class="input" bind:value={form.label} placeholder="Display name" /></label>
      </div>
      {#if kind === 'truck'}
        <label class="field"><span>Licence / registration no.</span><input class="input mono" bind:value={form.plate} placeholder="HR 26 AB 1234" /></label>
      {/if}
      {#if kind === 'site'}
        <label class="field"><span>Site type</span>
          <select class="select" bind:value={form.site_type}><option value="">Unknown</option><option>loading</option><option>unloading</option><option>depot</option></select>
        </label>
      {/if}
      <label class="field"><span>Remarks</span><input class="input" bind:value={form.notes} placeholder={kind === 'truck' ? 'Driver, owner, capacity…' : 'Optional'} /></label>
    </form>

    {#if form.id && kind !== 'verb'}
      <div class="section">
        <span class="field-label">Aliases <small class="mute">— other spellings that resolve to {form.code}</small></span>
        <div class="aliases">
          {#each aliasesOf(form.id) as a (a.id)}
            <span class="tag mono big" class:inactive={!a.active}>
              {a.code}
              <button title="Make separate again" onclick={() => unmerge(a)}><Icon name="unmerge" size={12} /></button>
              <button title="Delete alias" onclick={() => delAlias(a)}><Icon name="x" size={12} /></button>
            </span>
          {/each}
          <form class="alias-add" onsubmit={(e) => { e.preventDefault(); addAlias() }}>
            <input class="input sm mono" bind:value={newAlias} placeholder="Add alias" />
          </form>
        </div>
      </div>
      <div class="section">
        <span class="field-label">Merge {form.code} into…</span>
        <div class="row">
          <select class="select sm grow" bind:value={mergeInto}>
            <option value="">Choose {kind}</option>
            {#each canon.filter((x) => x.id !== form.id) as x}<option value={x.id}>{x.code}{x.label !== x.code ? ` — ${x.label}` : ''}</option>{/each}
          </select>
          <button class="btn quiet sm" disabled={!mergeInto} onclick={merge}><Icon name="merge" size={14} />Merge</button>
        </div>
        <p class="mute small">Past reports keep their original value; unmerge any time from the alias list.</p>
      </div>
    {/if}
    {#if error}<p class="notice err">{error}</p>{/if}
  {/if}
  {#snippet actions()}
    {#if form?.id}
      {#if !form.active}<button class="btn quiet" onclick={reactivate}>Reactivate</button>
      {:else}<button class="btn ghost danger" onclick={del}>Delete</button>{/if}
      <span class="grow"></span>
    {/if}
    <button class="btn ghost" onclick={() => (formOpen = false)}>Cancel</button>
    <button class="btn signal" type="submit" form="regform">Save</button>
  {/snippet}
</Modal>

<Modal bind:open={shiftOpen} title="Edit shift">
  {#if shiftForm}
    <label class="field"><span>Started · IST</span><input class="input" type="datetime-local" bind:value={shiftForm.started_at} /></label>
    <label class="field"><span>Ended · IST <small class="mute">(empty = still running)</small></span><input class="input" type="datetime-local" bind:value={shiftForm.ended_at} /></label>
    <p class="mute small">Reports move in or out of the shift automatically by their time.</p>
    {#if error}<p class="notice err">{error}</p>{/if}
  {/if}
  {#snippet actions()}
    <button class="btn ghost danger" onclick={deleteShift}>Delete shift</button>
    <span class="grow"></span>
    <button class="btn ghost" onclick={() => (shiftOpen = false)}>Cancel</button>
    <button class="btn signal" onclick={saveShift}>Save</button>
  {/snippet}
</Modal>

<style>
  .admin { display: flex; flex-direction: column; gap: 14px; padding-bottom: 36px; }
  .toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .count { font-size: 10.5px; color: var(--mute); margin-left: 2px; }
  .strong { font-weight: 650; }
  .small { font-size: 12.5px; }
  .nowrap { white-space: nowrap; }
  .plate { font-size: 12.5px; }
  .notes { color: var(--ink-2); max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .clickable tbody tr { cursor: pointer; }
  .clickable td.num :global(svg) { color: var(--mute); vertical-align: middle; margin-left: 6px; }
  .inactive { opacity: .5; }
  .type { width: auto; min-width: 120px; }
  .type.missing { border-color: var(--signal); color: var(--signal); }

  .tag {
    display: inline-flex; align-items: center; gap: 2px; height: 22px; padding: 0 7px; margin: 0 4px 2px 0; border-radius: 6px;
    background: var(--paper-2); font-size: 11.5px; color: var(--ink-2);
  }
  .tag.big { height: 30px; padding: 0 4px 0 10px; font-size: 12.5px; }
  .tag button { display: grid; place-items: center; width: 22px; height: 22px; border-radius: 5px; color: var(--mute); }
  .tag button:hover { background: var(--hair-2); color: var(--ink); }

  .stack { display: flex; flex-direction: column; gap: 14px; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .section { display: flex; flex-direction: column; gap: 8px; padding-top: 14px; border-top: 1px solid var(--hair-2); }
  .field-label { font-size: 13px; color: var(--ink-2); font-weight: 550; }
  .aliases { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
  .alias-add .input { width: 130px; }

  .settings { max-width: 720px; }
  .modes { border: 0; padding: 0; margin: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .modes legend { margin-bottom: 8px; }
  .mode {
    display: flex; flex-direction: column; gap: 4px; padding: 14px; border-radius: var(--r); cursor: pointer;
    box-shadow: inset 0 0 0 1px var(--hair); transition: box-shadow .15s, background .15s;
  }
  .mode input { position: absolute; opacity: 0; }
  .mode span { font-size: 13px; color: var(--mute); }
  .mode.on { box-shadow: inset 0 0 0 1.5px var(--ink); background: var(--surface); }

  .diff { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 6px; }
  .diff pre { margin: 0; padding: 8px; border-radius: 6px; font-size: 10.5px; white-space: pre-wrap; word-break: break-word; max-height: 240px; overflow: auto; }
  .before { background: var(--red-soft); }
  .after { background: var(--moss-soft); }

  @media (max-width: 640px) {
    .two, .modes, .diff { grid-template-columns: 1fr; }
  }
</style>
