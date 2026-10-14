<script>
  import ReportLog from '../lib/ReportLog.svelte'
  import { api } from '../lib/api.js'

  let { registry, me, tick, onChange } = $props()
  let scope = $state('mine') // admins: 'mine' | 'all'
  let items = $state(null)
  $effect(() => {
    tick
    const url = scope === 'all' ? '/api/reports?mine=false&limit=1000' : '/api/reports?limit=300'
    api.get(url).then((r) => (items = r))
  })
  const flagged = $derived(items?.filter((r) => r.flags.length).length || 0)
</script>

<div class="mine">
  <div class="top">
    {#if me.is_admin}
      <div class="seg">
        <button class:on={scope === 'mine'} onclick={() => (scope = 'mine')}>Mine</button>
        <button class:on={scope === 'all'} onclick={() => (scope = 'all')}>Everyone</button>
      </div>
    {/if}
    {#if items}
      <p class="lede">
        <b class="mono">{items.length}</b> reports
        {#if flagged}<span class="pill warn">{flagged} need a look</span>{/if}
      </p>
    {/if}
  </div>
  {#if items}
    <ReportLog {items} {registry} {me} {onChange} showUser={scope === 'all'}
      empty={scope === 'all' ? 'No reports yet.' : "You haven't reported anything yet."} />
  {/if}
</div>

<style>
  .mine { max-width: 860px; width: 100%; padding-bottom: 32px; }
  .top { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 18px; }
  .lede { display: flex; align-items: center; gap: 10px; color: var(--ink-2); }
</style>
