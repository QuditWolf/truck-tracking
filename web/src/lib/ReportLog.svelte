<script>
  import Icon from './Icon.svelte'
  import Modal from './Modal.svelte'
  import ReportForm from './ReportForm.svelte'
  import { api, dateTime, time } from './api.js'
  import { toast } from './stores.svelte.js'

  let { items, registry, me, onChange, showUser = false, empty = 'Nothing reported yet.' } = $props()

  let editing = $state(null)
  let deleting = $state(null)
  let editOpen = $state(false)
  let delOpen = $state(false)

  const day = (iso) => dateTime(iso).split(',')[0]
  const groups = $derived.by(() => {
    const out = []
    for (const r of items) {
      const d = day(r.event_time)
      if (!out.length || out.at(-1).day !== d) out.push({ day: d, rows: [] })
      out.at(-1).rows.push(r)
    }
    return out
  })
  const canEdit = (r) => r.user_id === me.id || me.is_admin

  function edit(r) { editing = r; editOpen = true }
  function ask(r) { deleting = r; delOpen = true }
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
        <li class:flagged={r.flags.length}>
          <time class="mono">{time(r.event_time)}</time>
          <div class="main">
            <p class="line mono">
              <span>{r.trucks.join(',')}</span>
              <span class="verb">{r.verb}</span>
              {#if r.site}<span>{r.site}</span>{/if}
            </p>
            {#if r.remarks}<p class="remark">{r.remarks}</p>{/if}
            {#each r.flags as f}<p class="flag"><Icon name="warn" size={13} />{f}</p>{/each}
          </div>
          <div class="side">
            {#if showUser}<span class="who">{r.user}</span>{/if}
            {#if r.source === 'wa'}<span class="pill plain">WA</span>{/if}
            {#if canEdit(r)}
              <div class="acts">
                <button class="btn ghost sm icon" title="Edit" onclick={() => edit(r)}><Icon name="edit" size={15} /></button>
                <button class="btn ghost sm icon danger" title="Delete" onclick={() => ask(r)}><Icon name="trash" size={15} /></button>
              </div>
            {/if}
          </div>
        </li>
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
