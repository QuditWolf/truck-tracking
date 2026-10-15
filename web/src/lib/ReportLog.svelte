<script>
  import Icon from './Icon.svelte'
  import Modal from './Modal.svelte'
  import ReportForm from './ReportForm.svelte'
  import { api, dateTime, time } from './api.js'
  import { toast } from './stores.svelte.js'

  // shifts: optional — shift start/end shown in the timeline (admins can delete / reopen)
  let { items, registry, me, onChange, showUser = false, empty = 'Nothing reported yet.', shifts = [] } = $props()

  let editing = $state(null)
  let deleting = $state(null)
  let editOpen = $state(false)
  let delOpen = $state(false)

  const day = (iso) => dateTime(iso).split(',')[0]
  const rows = $derived.by(() => {
    if (!shifts.length || !items.length) return items
    const oldest = items.at(-1).event_time
    const marks = shifts.flatMap((sh) => [
      { kind: 'shift', action: 'start', id: `s${sh.id}`, event_time: sh.started_at, shift: sh },
      ...(sh.ended_at ? [{ kind: 'shift', action: 'end', id: `e${sh.id}`, event_time: sh.ended_at, shift: sh }] : []),
    ]).filter((m) => m.event_time >= oldest)
    return [...items, ...marks].sort((a, b) => (a.event_time < b.event_time ? 1 : a.event_time > b.event_time ? -1 : 0))
  })
  const groups = $derived.by(() => {
    const out = []
    for (const r of rows) {
      const d = day(r.event_time)
      if (!out.length || out.at(-1).day !== d) out.push({ day: d, rows: [] })
      out.at(-1).rows.push(r)
    }
    return out
  })
  const canEdit = (r) => r.user_id === me.id || me.is_admin

  function edit(r) { editing = r; editOpen = true }
  function ask(r) { deleting = r; delOpen = true }
  async function restore(r) {
    try { await api.post(`/api/reports/${r.id}/restore`); toast('Report restored'); onChange() } catch (e) { toast(e.message, 'warn') }
  }

  let shiftAct = $state(null) // { action, shift }
  let shiftOpen = $state(false)
  async function doShift() {
    shiftOpen = false
    const { action, shift } = shiftAct
    try {
      await api.patch(`/api/shifts/${shift.id}`, action === 'start' ? { deleted: true } : { ended_at: '' })
      toast(action === 'start' ? 'Shift deleted' : 'Shift reopened')
      onChange()
    } catch (e) { toast(e.message, 'warn') }
  }

  async function remove() {
    delOpen = false
    await api.del(`/api/reports/${deleting.id}`)
    toast('Report deleted')
    onChange()
  }
</script>

{#if !items.length}
  <div class="empty-state"><Icon name="mine" size={22} /><p>{empty}</p></div>
{/if}

{#each groups as g (g.day)}
  <section class="day">
    <h4 class="eyebrow">{g.day}</h4>
    <ul class="stagger">
      {#each g.rows as r (r.id)}
        {#if r.kind === 'shift'}
        <li class="shiftrow">
          <time class="mono">{time(r.event_time)}</time>
          <div class="main"><p class="line">Shift {r.action === 'start' ? 'started' : 'ended'}{r.action === 'start' && r.shift.sites?.length ? ` · ${r.shift.sites.join(', ')}` : ''}</p></div>
          <div class="side">
            <span class="who">{r.action === 'start' ? r.shift.started_by : r.shift.ended_by}</span>
            {#if me.is_admin}
              <button class="btn ghost sm danger" onclick={() => { shiftAct = r; shiftOpen = true }}>{r.action === 'start' ? 'Delete shift' : 'Reopen'}</button>
            {/if}
          </div>
        </li>
        {:else}
        <li class:flagged={r.flags.length && !r.deleted} class:deleted={r.deleted}>
          <time class="mono">{time(r.event_time)}</time>
          <div class="main">
            <p class="line mono">
              <span>{r.trucks.join(',')}</span>
              <span class="verb">{r.verb}</span>
              {#if r.site}<span>{r.site}</span>{/if}
              {#if r.half}<span class="half">½</span>{/if}
            </p>
            {#if r.remarks}<p class="remark">{r.remarks}</p>{/if}
            {#each r.flags as f}<p class="flag"><Icon name="warn" size={13} />{f}</p>{/each}
          </div>
          <div class="side">
            {#if showUser}<span class="who">{r.user}</span>{/if}
            {#if r.source === 'wa'}<span class="pill plain">WA</span>{/if}
            {#if r.deleted}
              <span class="pill warn plain">deleted</span>
              {#if me.is_admin}<button class="btn quiet sm" onclick={() => restore(r)}>Restore</button>{/if}
            {:else if canEdit(r)}
              <div class="acts">
                <button class="btn ghost sm icon" title="Edit" onclick={() => edit(r)}><Icon name="edit" size={15} /></button>
                <button class="btn ghost sm icon danger" title="Delete" onclick={() => ask(r)}><Icon name="trash" size={15} /></button>
              </div>
            {/if}
          </div>
        </li>
        {/if}
      {/each}
    </ul>
  </section>
{/each}

<Modal bind:open={editOpen} title="Edit report">
  {#if editing}
    {#key editing.id}
      <ReportForm {registry} report={editing} {me} onDone={(r) => { editOpen = false; if (r) { toast('Report updated'); onChange() } }} />
    {/key}
  {/if}
</Modal>

<Modal bind:open={shiftOpen} title={shiftAct?.action === 'start' ? 'Delete this shift?' : 'Reopen this shift?'}>
  {#if shiftAct?.action === 'start'}
    <p>The shift that started {dateTime(shiftAct.shift.started_at)} is removed. Its reports stay, but no longer belong to a shift.</p>
  {:else if shiftAct}
    <p>The shift becomes open again (fails if another shift is running).</p>
  {/if}
  {#snippet actions()}
    <button class="btn ghost" onclick={() => (shiftOpen = false)}>Cancel</button>
    <button class="btn signal" onclick={doShift}>{shiftAct?.action === 'start' ? 'Delete shift' : 'Reopen'}</button>
  {/snippet}
</Modal>

<Modal bind:open={delOpen} title="Delete report?">
  {#if deleting}
    <p class="mono">{deleting.trucks.join(',')} {deleting.verb} {deleting.site || ''} {time(deleting.event_time)}</p>
    <p class="mute">It stays in the audit log, and the deletion is posted to WhatsApp.</p>
  {/if}
  {#snippet actions()}
    <button class="btn ghost" onclick={() => (delOpen = false)}>Keep</button>
    <button class="btn signal" onclick={remove}>Delete</button>
  {/snippet}
</Modal>

<style>
  .day { display: flex; flex-direction: column; gap: 8px; margin-bottom: 22px; }
  ul { list-style: none; margin: 0; padding: 0; border-radius: var(--r-lg); background: var(--surface);
       box-shadow: inset 0 0 0 1px var(--hair-2), var(--shadow); overflow: hidden; }
  li {
    display: grid; grid-template-columns: 52px 1fr auto; gap: 12px; align-items: start;
    padding: 12px 14px; border-top: 1px solid var(--hair-2); transition: background .15s;
  }
  li:first-child { border-top: 0; }
  li:hover { background: color-mix(in srgb, var(--paper) 55%, transparent); }
  li.flagged { box-shadow: inset 3px 0 0 var(--amber); }
  time { font-size: 12.5px; color: var(--mute); padding-top: 2px; }
  .main { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
  .line { display: flex; gap: 8px; flex-wrap: wrap; font-size: 14.5px; font-weight: 600; }
  .verb { color: var(--signal); }
  .half { color: var(--amber); }
  li.deleted { opacity: .55; }
  li.deleted .line { text-decoration: line-through; }
  li.shiftrow { background: color-mix(in srgb, var(--paper-2) 70%, transparent); }
  li.shiftrow .line { font-family: var(--sans); font-size: 13px; font-weight: 600; color: var(--ink-2); }
  .remark { font-size: 13.5px; color: var(--ink-2); }
  .flag { display: flex; gap: 6px; align-items: center; font-size: 12.5px; color: var(--amber); }
  .side { display: flex; align-items: center; gap: 8px; }
  .who { font-size: 13px; color: var(--mute); }
  .acts { display: flex; opacity: .55; transition: opacity .15s; }
  li:hover .acts, .acts:focus-within { opacity: 1; }
  @media (hover: none) { .acts { opacity: 1; } }
  @media (max-width: 520px) {
    li { grid-template-columns: 44px 1fr; }
    .side { grid-column: 2; justify-content: space-between; }
  }
</style>
