<script>
  let manual = $state()
  import Icon from '../lib/Icon.svelte'
  import ManualCounts from '../lib/ManualCounts.svelte'
  import Stat from '../lib/Stat.svelte'
  import { api, dateTime, halves, time, todayIST, waHtml } from '../lib/api.js'
  import { toast } from '../lib/stores.svelte.js'

  let { tick, registry, me, shiftParam = '' } = $props()

  let mode = $state('shift')
  let shifts = $state([])
  let shiftId = $state('') // '' = current (open, else latest)
  $effect(() => { if (shiftParam) { mode = 'shift'; shiftId = shiftParam } })
  let day = $state(todayIST())
  let from = $state(todayIST().slice(0, 8) + '01')
  let to = $state(todayIST())
  let data = $state(null)

  $effect(() => { tick; api.get('/api/shifts?limit=100').then((s) => (shifts = s)) })
  $effect(() => {
    tick
    const url =
      mode === 'shift' ? `/api/summary/shift${shiftId ? `?shift_id=${shiftId}` : ''}`
      : mode === 'day' ? `/api/summary/range?start=${day}`
      : `/api/summary/range?start=${from}&end=${to}`
    api.get(url).then((d) => (data = d))
  })

  // shifts come newest first; "current" = open shift, else the latest
  const curIdx = $derived(Math.max(0, shifts.findIndex((s) => !s.ended_at)))
  const prevId = $derived(shifts[curIdx + 1]?.id ?? null)
  const earlier = $derived(shifts.filter((_, i) => i !== curIdx && shifts[i].id !== prevId))
  const pick = $derived(shiftId === '' ? 'current' : +shiftId === prevId ? 'previous' : 'other')

  const c = $derived(data?.counts)
  const sites = $derived.by(() => {
    if (!c) return []
    const names = new Set([...Object.keys(c.loaded_by_site || {}), ...Object.keys(c.unloaded_by_site || {})])
    const rows = [...names].map((s) => ({ s, l: c.loaded_by_site?.[s] || 0, u: c.unloaded_by_site?.[s] || 0 }))
    return rows.sort((a, b) => b.l + b.u - (a.l + a.u))
  })
  const maxSite = $derived(Math.max(1, ...sites.map((r) => Math.max(r.l, r.u))))
  const trucks = $derived(c ? Object.entries(c.per_truck) : [])
  const fmt = (m) => (m == null ? '—' : m >= 60 ? `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, '0')}m` : `${m}m`)

  const SLOTS = [['ENTER', 'In'], ['LS', 'LS'], ['LO', 'LO'], ['LEFT', 'Out'], ['ENTER@U', 'In'], ['US', 'US'], ['UO', 'UO'], ['LEFT@U', 'Out']]

  async function copy() {
    try {
      await navigator.clipboard.writeText(data.text)
    } catch {
      // in-app browsers / non-secure contexts: fall back to a hidden textarea
      const ta = Object.assign(document.createElement('textarea'), { value: data.text })
      ta.style.cssText = 'position:fixed;opacity:0'
      document.body.append(ta)
      ta.select()
      const ok = document.execCommand('copy')
      ta.remove()
      if (!ok) return toast('Copy blocked — long-press the text to copy', 'warn')
    }
    toast('Summary copied')
  }

  // Phone: native share sheet (WhatsApp, groups...). Desktop: WhatsApp with the text prefilled.
  async function share() {
    if (navigator.share) {
      try { await navigator.share({ text: data.text }) } catch { /* dismissed */ }
    } else {
      window.open(`https://wa.me/?text=${encodeURIComponent(data.text)}`, '_blank', 'noopener')
    }
  }
</script>

<div class="summary">
  <div class="toolbar">
    <div class="seg">
      {#each [['shift', 'Shift'], ['day', 'Day'], ['range', 'Season']] as [k, label]}
        <button class:on={mode === k} onclick={() => (mode = k)}>{label}</button>
      {/each}
    </div>
    {#if mode === 'shift'}
      <div class="seg">
        <button class:on={pick === 'current'} onclick={() => (shiftId = '')}>Current</button>
        <button class:on={pick === 'previous'} disabled={!prevId} onclick={() => (shiftId = String(prevId))}>Previous</button>
      </div>
      {#if earlier.length}
        <select class="select sm pick" class:on={pick === 'other'} value={pick === 'other' ? shiftId : ''}
                onchange={(e) => (shiftId = e.target.value || '')}>
          <option value="">Earlier…</option>
          {#each earlier as s}<option value={String(s.id)}>{dateTime(s.started_at)} → {s.ended_at ? dateTime(s.ended_at) : 'running'}</option>{/each}
        </select>
      {/if}
    {:else if mode === 'day'}
      <input class="input sm pick" type="date" bind:value={day} />
    {:else}
      <input class="input sm pick" type="date" bind:value={from} />
      <span class="mute">to</span>
      <input class="input sm pick" type="date" bind:value={to} />
    {/if}
    <span class="grow"></span>
    {#if mode === 'shift' && data?.shift_id}
      <button class="btn quiet sm" onclick={() => manual?.start('unload')}><Icon name="plus" size={15} />Unload, no time</button>
    {/if}
    {#if data?.text}
      <button class="btn quiet sm" onclick={copy}><Icon name="copy" size={15} />Copy</button>
      <button class="btn signal sm" onclick={share}><Icon name="send" size={15} />Share to WhatsApp</button>
    {/if}
  </div>

  {#if c}
    <div class="stats stagger">
      <Stat label="Loaded" value={c.loaded} accent
        sub={[c.loaded_abs !== c.loaded ? `${halves(c.loaded_abs)} loads (half = ½)` : '', c.loaded_inf ? `${c.loaded_inf} inferred` : '',
             Object.keys(c.unlogged || {}).length ? `${c.loaded_with_unlogged} incl. unlogged ${Object.entries(c.unlogged).map(([t, n]) => n > 1 ? `${t}*${n}` : t).join(',')}` : ''].filter(Boolean).join(' · ') || 'all reported'} />
      <Stat label="Unloaded" value={c.unloaded}
        sub={[c.unloaded_abs !== c.unloaded ? `${halves(c.unloaded_abs)} loads (half = ½)` : '', c.unloaded_inf ? `${c.unloaded_inf} inferred` : ''].filter(Boolean).join(' · ') || 'all reported'} />
      <Stat label="Flags" value={c.flags} sub={c.flags ? 'check reports' : 'clean'} warn={c.flags > 0} />
    </div>

    <div class="grid">
      <section class="card sites">
        <div class="card-h"><h3>By site</h3><span class="legend"><i class="l"></i>Loaded <i class="u"></i>Unloaded</span></div>
        <div class="card-b">
          {#each sites as r (r.s)}
            <div class="bar-row">
              <span class="mono name">{r.s}</span>
              <div class="bars">
                {#if r.l}<div class="bar l" style:--w="{(r.l / maxSite) * 100}%"><span>{r.l}</span></div>{/if}
                {#if r.u}<div class="bar u" style:--w="{(r.u / maxSite) * 100}%"><span>{r.u}</span></div>{/if}
              </div>
            </div>
          {:else}
            <p class="mute">No loads yet.</p>
          {/each}
        </div>
      </section>

      <section class="card wa">
        <div class="card-h"><h3>{data.title}</h3>{#if data.open}<span class="pill live">Live</span>{/if}</div>
        <div class="card-b"><pre class="mono">{@html waHtml(data.text)}</pre></div>
      </section>

      <section class="card wide">
        <div class="card-h"><h3>Trucks</h3><span class="mute small">Average minutes from reported events</span></div>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Truck</th><th class="num">Trips</th><th class="num">Loads</th><th class="num">Unloads</th>
              {#if data.durations}<th class="num">Loading</th><th class="num">Haul</th><th class="num">Unloading</th><th class="num">Cycle</th>{/if}</tr></thead>
            <tbody>
              {#each trucks as [t, p] (t)}
                {@const d = data.durations?.per_truck[t]}
                <tr><td class="mono strong">{t}</td><td class="num">{p.trips}</td><td class="num">{p.loads}</td><td class="num">{p.unloads}</td>
                  {#if data.durations}<td class="num">{fmt(d?.loading)}</td><td class="num">{fmt(d?.haul)}</td><td class="num">{fmt(d?.unloading)}</td><td class="num">{fmt(d?.cycle)}</td>{/if}</tr>
              {/each}
            </tbody>
            {#if data.durations}
              {@const o = data.durations.overall}
              <tfoot><tr><td>Average</td><td></td><td></td><td></td><td class="num">{fmt(o.loading)}</td><td class="num">{fmt(o.haul)}</td><td class="num">{fmt(o.unloading)}</td><td class="num">{fmt(o.cycle)}</td></tr></tfoot>
            {/if}
          </table>
        </div>
      </section>

      {#if data.trips && Object.keys(data.trips).length}
        <section class="card wide">
          <div class="card-h"><h3>Trips</h3>
            <span class="legend"><i class="rep"></i>Reported <i class="gap"></i>Not reported <i class="dup"></i>Duplicates</span></div>
          <div class="card-b trips">
            {#each Object.entries(data.trips) as [truck, ts] (truck)}
              <div class="trip-row">
                <span class="mono strong">{truck}</span>
                <div class="trip-list">
                  {#each ts as t, i}
                    <div class="trip-card" class:carry={t.carry_in} class:dup={t.duplicates}>
                      <div class="trip-head">
                        <span class="mono">#{i + 1}</span>
                        <span class="route mono">{t.load_site || (t.carry_in ? 'carried' : '?')} → {t.unload_site || '…'}</span>
                        {#if t.loaded === 'inf'}<em>load inferred</em>{/if}
                        {#if t.unloaded === 'inf'}<em>unload inferred</em>{/if}
                        {#if t.duplicates}<em>{t.duplicates} dup</em>{/if}
                        {#if !t.closed}<span class="pill live">current</span>{/if}
                      </div>
                      <div class="trip">
                        {#each SLOTS as [k, lab]}
                          <span class="slot" class:on={t.slots[k]}>{t.slots[k] ? t.slots[k] : lab}</span>
                        {/each}
                      </div>
                    </div>
                  {/each}
                </div>
              </div>
            {/each}
          </div>
        </section>
      {/if}

      {#if data.remarks?.length}
        <section class="card wide">
          <div class="card-h"><h3>Remarks</h3><span class="mute small">{data.remarks.length}</span></div>
          <ul class="remarks">
            {#each data.remarks as r (r.id)}
              <li><span class="mono when">{time(r.event_time)}</span><span class="mono what">{r.trucks} {r.verb}{r.site ? ` ${r.site}` : ''}</span><span class="text">{r.remarks}</span><span class="mute small">{r.user}</span></li>
            {/each}
          </ul>
        </section>
      {/if}

      {#if mode === 'shift' && data.shift_id}
        <div class="wide"><ManualCounts bind:this={manual} shiftId={data.shift_id} entries={data.manual || []} perTruck={c.per_truck} {registry} {me} /></div>
      {/if}

      {#if c.notes?.length || data.flags?.length}
        <section class="card wide">
          <div class="card-h"><h3>What was inferred, and why</h3></div>
          <div class="card-b notes">
            {#each c.notes || [] as n}<p class="notice info">{n}</p>{/each}
            {#each data.flags || [] as f}<p class="notice"><Icon name="warn" size={14} />{f}</p>{/each}
          </div>
        </section>
      {/if}

      {#if data.per_shift?.length}
        <section class="card wide">
          <div class="card-h"><h3>Shifts</h3></div>
          <table class="table">
            <tbody>{#each data.per_shift as s}<tr><td>{s.title}</td><td class="num">{s.loaded} loaded</td><td class="num">{s.unloaded} unloaded</td></tr>{/each}</tbody>
          </table>
        </section>
      {/if}
    </div>
  {:else if data}
    <div class="empty-state"><Icon name="summary" size={22} /><p>{data.text || 'Nothing to summarise yet.'}</p></div>
  {/if}
</div>

<style>
  .summary { display: flex; flex-direction: column; gap: 18px; padding-bottom: 36px; }
  .toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .pick { width: auto; min-width: 150px; }
  select.pick.on { border-color: var(--ink); }
  .seg button:disabled { opacity: .4; }
  .small { font-size: 12.5px; }
  .strong { font-weight: 650; }

  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); gap: 12px; }
  .grid { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); gap: 12px; }
  .wide { grid-column: 1 / -1; }

  .legend { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--mute); flex-wrap: wrap; }
  .legend i { width: 10px; height: 10px; border-radius: 3px; display: inline-block; margin-left: 6px; }
  .legend .l { background: var(--ink); }
  .legend .u { background: var(--signal); }
  .legend .rep { background: var(--ink); }
  .legend .gap { background: transparent; box-shadow: inset 0 0 0 1px var(--hair); }
  .legend .dup { background: var(--amber-soft); box-shadow: inset 0 0 0 1px var(--amber); }

  .bar-row { display: grid; grid-template-columns: 92px 1fr; gap: 12px; align-items: center; padding: 6px 0; }
  .name { font-size: 12.5px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .bars { display: flex; flex-direction: column; gap: 3px; }
  .bar {
    height: 16px; width: var(--w); min-width: 26px; border-radius: 4px; display: flex; align-items: center; justify-content: flex-end;
    padding-right: 6px; transform-origin: left; animation: grow .7s var(--ease) both;
  }
  .bar span { font: 600 10.5px/1 var(--mono); color: #fff; }
  .bar.l { background: var(--ink); }
  .bar.u { background: var(--signal); }
  @keyframes grow { from { transform: scaleX(0); } }

  .wa pre { user-select: all; -webkit-user-select: all; }
  .wa pre {
    margin: 0; padding: 14px 16px; border-radius: var(--r); background: var(--paper); box-shadow: inset 0 0 0 1px var(--hair-2);
    font-size: 12.5px; line-height: 1.65; white-space: pre-wrap; color: var(--ink-2);
  }

  .trips { display: flex; flex-direction: column; gap: 10px; }
  .trip-row { display: grid; grid-template-columns: minmax(34px, max-content) 1fr; gap: 10px; align-items: start; }
  .trip-row > .mono { padding-top: 5px; }
  .trip-list { display: flex; flex-wrap: wrap; gap: 8px; }
  .trip-card { display: flex; flex-direction: column; gap: 5px; padding: 8px; border-radius: 10px; background: var(--surface); box-shadow: inset 0 0 0 1px var(--hair-2); }
  .trip-card.carry { background: repeating-linear-gradient(-45deg, var(--surface), var(--surface) 5px, var(--paper) 5px, var(--paper) 10px); }
  .trip-card.dup { box-shadow: inset 0 0 0 1px var(--amber); }
  .trip-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12px; }
  .trip-head .mono { font-weight: 600; }
  .trip-head .route { color: var(--ink-2); font-weight: 500; }
  .trip-head em { font-style: normal; color: var(--amber); font-size: 11.5px; }
  .remarks { list-style: none; margin: 0; padding: 0 0 6px; }
  .remarks li { display: grid; grid-template-columns: 44px auto 1fr auto; gap: 12px; align-items: baseline; padding: 8px 16px; border-top: 1px solid var(--hair-2); font-size: 13.5px; }
  .remarks .when { font-size: 12px; color: var(--mute); }
  .remarks .what { font-weight: 600; font-size: 12.5px; }
  @media (max-width: 640px) { .remarks li { grid-template-columns: 40px 1fr; } .remarks .text, .remarks li > .mute { grid-column: 2; } }
  .trip { display: grid; grid-template-columns: repeat(8, auto); gap: 2px; }
  .slot {
    font: 500 9.5px/1 var(--mono); padding: 5px 5px; border-radius: 5px; color: var(--mute); min-width: 30px; text-align: center;
    box-shadow: inset 0 0 0 1px var(--hair-2);
  }
  .slot.on { background: var(--ink); color: var(--paper); box-shadow: none; font-weight: 600; }

  .notes { display: flex; flex-direction: column; gap: 6px; }

  @media (max-width: 640px) {
    .trip { grid-template-columns: repeat(4, auto); }  /* loading half / unloading half on two rows */
    .slot { min-width: 0; }
  }
  @media (max-width: 1000px) {
    .grid { grid-template-columns: minmax(0, 1fr); }
    .stats { gap: 8px; }
  }
</style>
