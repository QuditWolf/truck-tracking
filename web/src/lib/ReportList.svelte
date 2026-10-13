<script>
  import ReportForm from './ReportForm.svelte'
  import { api, dateTime, line } from './api.js'

  let { items, registry, me, onChange, showUser = false } = $props()
  let editing = $state(null)

  async function remove(r) {
    if (!confirm(`Delete "${line(r)}"? This is relayed to WhatsApp.`)) return
    await api.del(`/api/reports/${r.id}`)
    onChange()
  }
</script>

<ul class="reports">
  {#each items as r (r.id)}
    <li class:flagged={r.flags.length}>
      {#if editing === r.id}
        <ReportForm {registry} report={r} onDone={(x) => { editing = null; if (x) onChange() }} />
      {:else}
        <div class="head">
          <strong>{line(r)}</strong>
          <span class="muted">{dateTime(r.event_time)}{showUser ? ` · ${r.user}` : ''}{r.source === 'wa' ? ' · WA' : ''}</span>
        </div>
        {#if r.remarks}<p class="remark">- {r.remarks}</p>{/if}
        {#each r.flags as f}<p class="warn">{f}</p>{/each}
        {#if r.user_id === me.id || me.is_admin}
          <div class="actions">
            <button class="small ghost" onclick={() => (editing = r.id)}>Edit</button>
            <button class="small ghost danger" onclick={() => remove(r)}>Delete</button>
          </div>
        {/if}
      {/if}
    </li>
  {:else}
    <li class="muted">Nothing yet.</li>
  {/each}
</ul>
