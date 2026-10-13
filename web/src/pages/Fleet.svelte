<script>
  import FleetBoard from '../lib/FleetBoard.svelte'
  import ReportLog from '../lib/ReportLog.svelte'
  import { api } from '../lib/api.js'

  let { registry, me, tick, onChange } = $props()
  let feed = $state(null)
  $effect(() => { tick; api.get('/api/feed?limit=80').then((f) => (feed = f)) })
</script>

<div class="fleet">
  <FleetBoard {tick} />
  <section>
    <h2 class="eyebrow">Latest reports · everyone</h2>
    {#if feed}<ReportLog items={feed} {registry} {me} {onChange} showUser />{/if}
  </section>
</div>

<style>
  .fleet { display: flex; flex-direction: column; gap: 28px; padding-bottom: 32px; }
  section { display: flex; flex-direction: column; gap: 12px; }
  @media (min-width: 1280px) {
    .fleet { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); align-items: start; gap: 40px; }
  }
</style>
