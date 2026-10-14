<script>
  // Hand-added loads/unloads for trucks nobody reported (untracked trucks). Any member can add.
  import Icon from './Icon.svelte'
  import Modal from './Modal.svelte'
  import Picker from './Picker.svelte'
  import { api, time } from './api.js'
  import { toast } from './stores.svelte.js'

  let { shiftId, entries = [], registry, me } = $props()

  let open = $state(false)
  let truck = $state('')
  let kind = $state('load')
  let count = $state(1)
  let site = $state('')
  let note = $state('')
  let busy = $state(false)
  let error = $state('')

  function start() {
    truck = ''; kind = 'load'; count = 1; site = registry.shift?.default_site || ''; note = ''; error = ''
    open = true
  }

  async function save() {
    busy = true
    error = ''
    try {
      await api.post('/api/manual', { truck, kind, count, site: site || null, note, shift_id: shiftId })
      toast(`${truck} +${count} ${kind}${count > 1 ? 's' : ''} added`)
      open = false
    } catch (e) {
      error = e.message
    } finally {
      busy = false
    }
  }

  async function remove(m) {
    try {
      await api.del(`/api/manual/${m.id}`)
      toast('Removed')
    } catch (e) { toast(e.message, 'warn') }
  }
</script>

<section class="card manual">
  <div class="card-h">
    <div>
      <h3>Untracked trucks</h3>
      <span class="mute small">Loads or unloads nobody reported, added by hand</span>
    </div>
    <button class="btn quiet sm" onclick={start}><Icon name="plus" size={14} />Add</button>
  </div>
  {#if entries.length}
    <ul>
      {#each entries as m (m.id)}
        <li>
          <span class="mono line"><b>{m.truck}</b> +{m.count} {m.kind}{m.count > 1 ? 's' : ''}{m.site ? ` ${m.site}` : ''}</span>
          <span class="mute small">{m.note ? `${m.note} · ` : ''}{m.user} · {time(m.created_at)}</span>
          {#if m.user_id === me.id || me.is_admin}
            <button class="btn ghost sm icon danger" title="Remove" onclick={() => remove(m)}><Icon name="trash" size={14} /></button>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</section>

<Modal bind:open title="Add untracked truck">
  <form class="stack" id="manualform" onsubmit={(e) => { e.preventDefault(); save() }}>
    <Picker label="Truck" options={registry.truck} bind:value={truck} placeholder="Truck / reg. no." />
    <div class="row2">
      <div class="seg">
        <button type="button" class:on={kind === 'load'} onclick={() => (kind = 'load')}>Loads</button>
        <button type="button" class:on={kind === 'unload'} onclick={() => (kind = 'unload')}>Unloads</button>
      </div>
      <div class="stepper">
        <button type="button" class="btn quiet sm icon" onclick={() => (count = Math.max(1, count - 1))} aria-label="Less">−</button>
        <span class="mono">{count}</span>
        <button type="button" class="btn quiet sm icon" onclick={() => (count = Math.min(50, count + 1))} aria-label="More">+</button>
      </div>
    </div>
    <Picker label="Site (optional)" options={registry.site} bind:value={site} variant="labelled" />
    <input class="input" bind:value={note} placeholder="Note — optional (e.g. contractor truck)" maxlength="120" />
    {#if error}<p class="notice err">{error}</p>{/if}
  </form>
  {#snippet actions()}
    <button class="btn ghost" onclick={() => (open = false)}>Cancel</button>
    <button class="btn signal" type="submit" form="manualform" disabled={!truck || busy}>Add to summary</button>
  {/snippet}
</Modal>

<style>
  .small { font-size: 12.5px; }
  .card-h > div { display: flex; flex-direction: column; gap: 2px; }
  ul { list-style: none; margin: 0; padding: 0 0 6px; }
  li { display: grid; grid-template-columns: auto 1fr auto; gap: 12px; align-items: center; padding: 8px 16px; border-top: 1px solid var(--hair-2); }
  .line { font-size: 13.5px; }
  .stack { display: flex; flex-direction: column; gap: 16px; }
  .row2 { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; }
  .stepper { display: flex; align-items: center; gap: 10px; }
  .stepper .mono { font-size: 18px; font-weight: 600; min-width: 24px; text-align: center; }
  @media (max-width: 520px) { li { grid-template-columns: 1fr auto; } li .mute { grid-column: 1; } }
</style>
