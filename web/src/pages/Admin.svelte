<script>
  import { api, dateTime, localInput } from '../lib/api.js'

  let tab = $state('registry')
  let items = $state([])
  let users = $state([])
  let settings = $state({})
  let shifts = $state([])
  let audit = $state([])
  let error = $state('')
  let kind = $state('truck')
  let newCode = $state('')
  let newLabel = $state('')
  let newType = $state('')

  async function load() {
    error = ''
    try {
      if (tab === 'registry') items = await api.get('/api/admin/registry')
      if (tab === 'users') users = await api.get('/api/admin/users')
      if (tab === 'settings') settings = await api.get('/api/admin/settings')
      if (tab === 'shifts') shifts = await api.get('/api/shifts?limit=100')
      if (tab === 'audit') audit = await api.get('/api/admin/audit')
    } catch (e) { error = e.message }
  }
  $effect(() => { tab; load() })

  async function run(fn) {
    error = ''
    try { await fn(); await load() } catch (e) { error = e.message }
  }

  const canon = $derived(items.filter((i) => i.kind === kind && !i.merged_into))
  const aliasesOf = (id) => items.filter((i) => i.merged_into === id)

  const add = () => run(async () => {
    await api.post('/api/admin/registry', { kind, code: newCode, label: newLabel, site_type: kind === 'site' ? newType || null : null })
    newCode = newLabel = ''
  })
  const patch = (i, body) => run(() => api.patch(`/api/admin/registry/${i.id}`, body))
  const del = (i) => confirm(`Delete ${i.code}? (kept as inactive if used anywhere)`) &&
    run(async () => { const r = await api.del(`/api/admin/registry/${i.id}`); if (r.result === 'deactivated') alert(`${i.code} is in use — deactivated instead`) })
  const alias = (i) => { const code = prompt(`New alias for ${i.code}`); if (code) run(() => api.post(`/api/admin/registry/${i.id}/alias`, { code })) }
  const rename = (i) => { const code = prompt('Code', i.code); if (code && code !== i.code) patch(i, { code }) }
  const relabel = (i) => { const label = prompt('Label', i.label); if (label != null && label !== i.label) patch(i, { label }) }
  const merge = (i, into) => into && confirm(`Merge ${i.code} into ${items.find((x) => x.id === +into).code}? Reports keep their original value and can be unmerged.`) &&
    run(() => api.post(`/api/admin/registry/${i.id}/merge`, { into: +into }))
  const unmerge = (i) => run(() => api.post(`/api/admin/registry/${i.id}/unmerge`))
  const editShift = (s, field) => {
    const v = prompt(`${field} (YYYY-MM-DDTHH:mm IST${field === 'ended_at' ? ', empty = reopen' : ''})`, s[field] ? localInput(s[field]) : '')
    if (v !== null) run(() => api.patch(`/api/shifts/${s.id}`, { [field]: v }))
  }
</script>

<div class="seg">
  {#each ['registry', 'shifts', 'users', 'settings', 'audit'] as t}
    <button class:on={tab === t} onclick={() => (tab = t)}>{t}</button>
  {/each}
</div>
{#if error}<p class="error">{error}</p>{/if}

{#if tab === 'registry'}
  <div class="seg small">
    {#each ['truck', 'site', 'verb'] as k}<button class:on={kind === k} onclick={() => (kind = k)}>{k}s</button>{/each}
  </div>
  <form class="row" onsubmit={(e) => { e.preventDefault(); add() }}>
    <input bind:value={newCode} placeholder="Code" required />
    <input bind:value={newLabel} placeholder="Label" />
    {#if kind === 'site'}
      <select bind:value={newType}><option value="">type?</option><option>loading</option><option>unloading</option><option>depot</option></select>
    {/if}
    <button>Add</button>
  </form>
  <ul class="registry">
    {#each canon as i (i.id)}
      <li class:inactive={!i.active}>
        <div class="row">
          <button type="button" class="link code" onclick={() => rename(i)}>{i.code}</button>
          <button type="button" class="link muted" onclick={() => relabel(i)}>{i.label}</button>
          {#if kind === 'site'}
            <select value={i.site_type || ''} onchange={(e) => patch(i, { site_type: e.target.value || null })}
                    class:missing={!i.site_type}>
              <option value="">type?</option><option>loading</option><option>unloading</option><option>depot</option>
            </select>
          {/if}
          {#if !i.active}<button class="small" onclick={() => patch(i, { active: true })}>Reactivate</button>{/if}
          <button class="small ghost danger end" onclick={() => del(i)}>Delete</button>
        </div>
        {#if kind !== 'verb'}
          <div class="row aliases">
            {#each aliasesOf(i.id) as a (a.id)}
              <span class="tag" class:inactive={!a.active}>
                <button type="button" class="link" onclick={() => rename(a)}>{a.code}</button>
                <button class="x" title="Unmerge (make separate again)" onclick={() => unmerge(a)}>↗</button>
                <button class="x" title="Delete alias" onclick={() => del(a)}>×</button>
              </span>
            {/each}
            <button class="small ghost" onclick={() => alias(i)}>+ alias</button>
            <select onchange={(e) => { merge(i, e.target.value); e.target.value = '' }}>
              <option value="">merge into…</option>
              {#each canon.filter((x) => x.id !== i.id) as x}<option value={x.id}>{x.code}</option>{/each}
            </select>
          </div>
        {/if}
      </li>
    {/each}
  </ul>
{:else if tab === 'shifts'}
  <table><tbody>
    <tr><th>Start</th><th>End</th><th>Site</th><th></th></tr>
    {#each shifts as s}
      <tr>
        <td><button class="link" onclick={() => editShift(s, 'started_at')}>{dateTime(s.started_at)}</button></td>
        <td><button class="link" onclick={() => editShift(s, 'ended_at')}>{s.ended_at ? dateTime(s.ended_at) : 'open'}</button></td>
        <td>{s.default_site || ''}</td>
        <td><button class="small ghost danger" onclick={() => confirm('Delete shift? Its events become unshifted.') && run(() => api.patch(`/api/shifts/${s.id}`, { deleted: true }))}>×</button></td>
      </tr>
    {/each}
  </tbody></table>
{:else if tab === 'users'}
  <table><tbody>
    <tr><th>Name</th><th>Phone</th><th>Email</th><th>Reports</th><th></th></tr>
    {#each users as u}
      <tr class:inactive={u.disabled}>
        <td>{u.name || '—'}{u.is_admin ? ' (admin)' : ''}</td><td>{u.phone || ''}</td><td>{u.email}</td><td>{u.reports}</td>
        <td>{#if !u.is_admin}<button class="small ghost" onclick={() => run(() => api.patch(`/api/admin/users/${u.id}`, { disabled: !u.disabled }))}>{u.disabled ? 'Enable' : 'Disable'}</button>{/if}</td>
      </tr>
    {/each}
  </tbody></table>
{:else if tab === 'settings'}
  <form class="stack" onsubmit={(e) => { e.preventDefault(); run(() => api.put('/api/admin/settings', settings)) }}>
    <label>Fleet group mode
      <select bind:value={settings.fleet_mode}>
        <option value="silent">silent — fleet group gets relays only</option>
        <option value="full">full — confirmations + summaries in fleet group too</option>
      </select>
    </label>
    <label>Summary every (min)<input type="number" min="0" bind:value={settings.summary_interval_min} /></label>
    <label>Warn if shift open longer than (h)<input type="number" min="1" bind:value={settings.shift_stale_hours} /></label>
    <button>Save</button>
  </form>
{:else}
  <table class="audit"><tbody>
    {#each audit as a}
      <tr><td>{dateTime(a.at)}</td><td>{a.action} {a.entity} {a.entity_id ?? ''}</td>
        <td><details><summary>diff</summary><pre>{a.before}</pre><pre>{a.after}</pre></details></td></tr>
    {/each}
  </tbody></table>
{/if}
