<script>
  import ReportLog from '../lib/ReportLog.svelte'
  import { api } from '../lib/api.js'

  let { registry, me, tick, onChange } = $props()
  let items = $state(null)
  $effect(() => { tick; api.get('/api/reports?limit=300').then((r) => (items = r)) })
  const flagged = $derived(items?.filter((r) => r.flags.length).length || 0)
</script>

<div class="mine">
  {#if items}
    <p class="lede">
      <b class="mono">{items.length}</b> reports
      {#if flagged}<span class="pill warn">{flagged} need a look</span>{/if}
    </p>
    <ReportLog {items} {registry} {me} {onChange} empty="You haven't reported anything yet." />
  {/if}
</div>

<style>
  .mine { max-width: 860px; width: 100%; padding-bottom: 32px; }
  .lede { display: flex; align-items: center; gap: 10px; margin-bottom: 18px; color: var(--ink-2); }
</style>
