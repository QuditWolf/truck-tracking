<script>
  import ReportLog from '../lib/ReportLog.svelte'
  import Toggle from '../lib/Toggle.svelte'
  import { api } from '../lib/api.js'

  let { registry, me, tick, onChange } = $props()
  let onlyMine = $state(false) // default: everyone's reports
  let showDeleted = $state(false) // admins: include deleted reports (restorable)
  let items = $state(null)
  let shifts = $state([])
  $effect(() => {
    tick
    const del = showDeleted ? '&include_deleted=true' : ''
    api.get((onlyMine ? '/api/reports?limit=300' : '/api/reports?mine=false&limit=1000') + del).then((r) => (items = r))
    api.get('/api/shifts?limit=100').then((s) => (shifts = s))
  })
  const flagged = $derived(items?.filter((r) => r.flags.length).length || 0)
</script>

<div class="mine">
  <div class="top">
    <div class="only"><Toggle checked={onlyMine} label="Only mine" onchange={(v) => (onlyMine = v)} /></div>
    {#if me.is_admin}<label class="check"><input type="checkbox" bind:checked={showDeleted} /> Show deleted</label>{/if}
    {#if items}
      <p class="lede">
        <b class="mono">{items.length}</b> reports
        {#if flagged}<span class="pill warn">{flagged} need a look</span>{/if}
      </p>
    {/if}
  </div>
  {#if items}
    <!-- edit/delete buttons appear only on your own reports (admins: all) -->
    <ReportLog {items} {registry} {me} {onChange} showUser={!onlyMine} shifts={onlyMine ? [] : shifts}
      empty={onlyMine ? "You haven't reported anything yet." : 'No reports yet.'} />
  {/if}
</div>

<style>
  .mine { max-width: 860px; width: 100%; padding-bottom: 32px; }
  .top { display: flex; align-items: center; justify-content: space-between; gap: 14px; flex-wrap: wrap; margin-bottom: 14px; }
  .only { min-width: 180px; }
  .only :global(.toggle) { padding: 4px 0; gap: 10px; }
  .lede { display: flex; align-items: center; gap: 10px; color: var(--ink-2); }
</style>
