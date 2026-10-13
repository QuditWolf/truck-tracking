<script>
  import { api, dateTime, localInput } from './api.js'

  let { shift, sites, onChange } = $props()
  let open = $state(false)
  let site = $state('')
  let at = $state('')
  let error = $state('')

  async function act(path, body) {
    error = ''
    try {
      await api.post(path, body)
      open = false
      at = ''
      onChange()
    } catch (e) { error = e.message }
  }
</script>

<div class="shiftbar" class:none={!shift}>
  {#if shift}
    <span>Shift since {dateTime(shift.started_at)}{shift.default_site ? ` · ${shift.default_site}` : ''}</span>
  {:else}
    <span>No active shift</span>
  {/if}
  <button class="small" onclick={() => (open = !open)}>{shift ? 'End / new' : 'Start'}</button>
</div>
{#if open}
  <div class="panel stack">
    <label>Default site
      <select bind:value={site}>
        <option value="">—</option>
        {#each sites as s}<option value={s.code}>{s.code} {s.label !== s.code ? `· ${s.label}` : ''}</option>{/each}
      </select>
    </label>
    <label>Time (IST, empty = now)<input type="datetime-local" bind:value={at} max={localInput()} /></label>
    <div class="actions">
      {#if shift}<button class="ghost" onclick={() => act('/api/shifts/end', { at: at || null })}>End shift</button>{/if}
      <button onclick={() => act('/api/shifts/start', { site: site || null, at: at || null })}>Start {shift ? 'new ' : ''}shift</button>
    </div>
    {#if error}<p class="error">{error}</p>{/if}
  </div>
{/if}
