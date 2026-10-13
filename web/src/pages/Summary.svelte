<script>
  import { api, dateTime, todayIST } from '../lib/api.js'

  let mode = $state('shift')
  let shifts = $state([])
  let shiftId = $state('')
  let day = $state(todayIST())
  let from = $state(todayIST())
  let to = $state(todayIST())
  let data = $state(null)
  let copied = $state(false)

  api.get('/api/shifts').then((s) => (shifts = s))

  $effect(() => {
    const url =
      mode === 'shift' ? `/api/summary/shift${shiftId ? `?shift_id=${shiftId}` : ''}`
      : mode === 'day' ? `/api/summary/range?start=${day}`
      : `/api/summary/range?start=${from}&end=${to}`
    api.get(url).then((d) => (data = d))
  })

  const c = $derived(data?.counts)
  const sites = (o) => Object.entries(o || {}).sort((a, b) => b[1] - a[1])
  const fmtMin = (m) => (m == null ? '–' : m >= 60 ? `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}` : `${m}m`)

  async function copy() {
    await navigator.clipboard.writeText(data.text)
    copied = true
    setTimeout(() => (copied = false), 1500)
  }
</script>

<div class="seg">
  {#each [['shift', 'Shift'], ['day', 'Day'], ['range', 'Season']] as [k, label]}
    <button class:on={mode === k} onclick={() => (mode = k)}>{label}</button>
  {/each}
</div>

{#if mode === 'shift'}
  <select bind:value={shiftId}>
    <option value="">Current / latest</option>
    {#each shifts as s}<option value={s.id}>{dateTime(s.started_at)} – {s.ended_at ? dateTime(s.ended_at) : 'open'}</option>{/each}
  </select>
{:else if mode === 'day'}
  <input type="date" bind:value={day} />
{:else}
  <div class="row"><input type="date" bind:value={from} /><input type="date" bind:value={to} /></div>
{/if}

{#if data?.text}
  <pre class="wa">{data.text}</pre>
  <button class="small ghost" onclick={copy}>{copied ? 'Copied' : 'Copy text'}</button>
{/if}

{#if c}
  <div class="cards">
    <div><b>{c.loaded}</b><span>Loaded{c.loaded_inf ? ` (${c.loaded_inf} inf)` : ''}</span></div>
    <div><b>{c.reached}</b><span>Reached</span></div>
    <div><b>{c.unloaded}</b><span>Unloaded{c.unloaded_inf ? ` (${c.unloaded_inf} inf)` : ''}</span></div>
    <div><b>{c.flags}</b><span>Flags</span></div>
  </div>

  <div class="two">
    <table><caption>Loaded by site</caption><tbody>{#each sites(c.loaded_by_site) as [s, n]}<tr><td>{s}</td><td>{n}</td></tr>{/each}</tbody></table>
    <table><caption>Unloaded by site</caption><tbody>{#each sites(c.unloaded_by_site) as [s, n]}<tr><td>{s}</td><td>{n}</td></tr>{/each}</tbody></table>
  </div>

  <div class="scroll"><table>
    <caption>Per truck</caption><tbody>
    <tr><th>Truck</th><th>Trips</th><th>Loads</th><th>Unloads</th>{#if data.durations}<th>Load</th><th>Haul</th><th>Unload</th><th>Cycle</th>{/if}</tr>
    {#each Object.entries(c.per_truck) as [t, p]}
      {@const d = data.durations?.per_truck[t]}
      <tr><td>{t}</td><td>{p.trips}</td><td>{p.loads}</td><td>{p.unloads}</td>
        {#if d}<td>{fmtMin(d.loading)}</td><td>{fmtMin(d.haul)}</td><td>{fmtMin(d.unloading)}</td><td>{fmtMin(d.cycle)}</td>{/if}</tr>
    {/each}
    {#if data.durations}
      {@const o = data.durations.overall}
      <tr class="total"><td>Avg</td><td></td><td></td><td></td><td>{fmtMin(o.loading)}</td><td>{fmtMin(o.haul)}</td><td>{fmtMin(o.unloading)}</td><td>{fmtMin(o.cycle)}</td></tr>
    {/if}
  </tbody></table></div>

  {#if c.notes?.length}
    <h3>Inferred</h3>
    <ul class="plain">{#each c.notes as n}<li>{n}</li>{/each}</ul>
  {/if}
  {#if data.flags?.length}
    <h3>Flags</h3>
    <ul class="plain warnlist">{#each data.flags as f}<li>{f}</li>{/each}</ul>
  {/if}

  {#if data.trips}
    <h3>Trips</h3>
    {#each Object.entries(data.trips) as [truck, ts]}
      <div class="trips">
        <b>{truck}</b>
        {#each ts as t}
          <span class="trip" class:carry={t.carry_in}>
            {#each Object.entries(t.slots) as [k, v]}<i>{k} {v}</i>{/each}
            {#if t.loaded === 'inf'}<em>load inf</em>{/if}
            {#if t.unloaded === 'inf'}<em>unload inf</em>{/if}
            {#if t.duplicates}<em>{t.duplicates} dup</em>{/if}
          </span>
        {/each}
      </div>
    {/each}
  {/if}

  {#if data.per_shift}
    <table>
      <caption>Shifts</caption><tbody>
      {#each data.per_shift as s}<tr><td>{s.title}</td><td>{s.loaded} loaded</td><td>{s.unloaded} unloaded</td></tr>{/each}
    </tbody></table>
  {/if}
{/if}
