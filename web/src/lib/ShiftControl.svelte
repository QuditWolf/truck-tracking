<script>
  import Modal from './Modal.svelte'
  import { api, dateTime, localInput, time } from './api.js'
  import { toast } from './stores.svelte.js'

  let { shift, sites, onChange } = $props()
  let open = $state(false)
  let site = $state('')
  let at = $state('')
  let error = $state('')

  function show() { site = shift?.default_site || ''; at = ''; error = ''; open = true }

  async function act(path, body, msg) {
    error = ''
    try {
      await api.post(path, body)
      open = false
      toast(msg)
      onChange()
    } catch (e) { error = e.message }
  }
</script>

<button class="shift" class:on={!!shift} onclick={show}>
  <span class="pill" class:live={!!shift} class:warn={!shift}>{shift ? 'Shift' : 'No shift'}</span>
  {#if shift}<span class="mono txt"><span class="since">since </span>{time(shift.started_at)}{shift.default_site ? ` · ${shift.default_site}` : ''}</span>{/if}
</button>

<Modal bind:open title={shift ? 'Shift' : 'Start shift'}>
  {#if shift}<p>Running since <b>{dateTime(shift.started_at)}</b>{shift.default_site ? ` · default site ${shift.default_site}` : ''}.</p>{/if}
  <label class="field"><span>Default site</span>
    <select class="select" bind:value={site}>
      <option value="">None</option>
      {#each sites as s}<option value={s.code}>{s.code}{s.label !== s.code ? ` — ${s.label}` : ''}</option>{/each}
    </select>
  </label>
  <label class="field"><span>Time · IST <small class="mute">(empty = now)</small></span>
    <input class="input" type="datetime-local" bind:value={at} max={localInput()} />
  </label>
  {#if error}<p class="notice err">{error}</p>{/if}
  {#snippet actions()}
    {#if shift}<button class="btn quiet" onclick={() => act('/api/shifts/end', { at: at || null }, 'Shift ended')}>End shift</button>{/if}
    <button class="btn signal" onclick={() => act('/api/shifts/start', { site: site || null, at: at || null }, 'Shift started')}>
      {shift ? 'End & start new' : 'Start shift'}
    </button>
  {/snippet}
</Modal>

<style>
  .shift {
    display: inline-flex; align-items: center; gap: 8px; height: 34px; padding: 0 12px 0 6px; border-radius: 99px;
    background: var(--surface); box-shadow: inset 0 0 0 1px var(--hair); font-size: 12px; color: var(--ink-2);
    transition: box-shadow .15s; white-space: nowrap; max-width: 100%; min-width: 0; overflow: hidden;
  }
  .txt { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  @media (max-width: 400px) { .since { display: none; } }
  .shift:not(.on) { padding-right: 6px; }
  .shift:hover { box-shadow: inset 0 0 0 1px var(--ink-2); }
</style>
