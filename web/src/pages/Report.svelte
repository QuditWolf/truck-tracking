<script>
  import FleetBoard from '../lib/FleetBoard.svelte'
  import ReportForm from '../lib/ReportForm.svelte'
  import { line } from '../lib/api.js'
  import { toast } from '../lib/stores.svelte.js'

  let { registry, me, tick, onChange } = $props()

  function sent(r, startedShift) {
    toast(startedShift ? `Shift started · ${line(r)}` : `Sent · ${line(r)}`)
    onChange()
  }
</script>

<div class="report">
  <div class="compose">
    {#key registry.shift?.id}
      <ReportForm {registry} {me} onDone={sent} />
    {/key}
  </div>
  <aside class="live">
    <FleetBoard {tick} />
  </aside>
</div>

<style>
  .report { flex: 1; display: grid; grid-template-columns: minmax(0, 1fr); gap: 32px; }
  .compose { display: flex; flex-direction: column; min-width: 0; }
  .compose :global(.composer) { flex: 1; }
  .live { display: none; }
  @media (min-width: 1180px) {
    .report { grid-template-columns: minmax(0, 1.1fr) minmax(320px, .9fr); }
    .live {
      display: block; position: sticky; top: 0; align-self: start; padding: 4px 0 24px 32px;
      border-left: 1px solid var(--hair-2); max-height: calc(100dvh - var(--top-h) - 20px); overflow-y: auto;
    }
  }
</style>
