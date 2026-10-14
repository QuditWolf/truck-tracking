<script>
  // Hand-added loads/unloads for trucks nobody reported (untracked trucks). Any member can add.
  import Icon from './Icon.svelte'
  import Modal from './Modal.svelte'
  import Picker from './Picker.svelte'
  import { api, time } from './api.js'
  import { toast } from './stores.svelte.js'

  // perTruck: current counts for this shift, so the dialog can show what each entry adds up to
  let { shiftId, entries = [], registry, me, perTruck = {} } = $props()

  let open = $state(false)
  let trucks = $state([])
  let kind = $state('load')
  let count = $state(1)
  let site = $state('')
  let note = $state('')
  let postFleet = $state(true)
  let busy = $state(false)
  let error = $state('')

  function start() {
    trucks = []; kind = 'load'; count = 1; site = registry.site.find((x) => x.code === registry.shift?.default_site && x.site_type === 'loading')?.code || ''; note = ''; postFleet = true; error = ''
    open = true
  }

  async function save() {
    busy = true
    error = ''
    try {
      await api.post('/api/manual', { trucks, kind, count, site: site || null, note, post_fleet: postFleet, shift_id: shiftId })
      toast(`${trucks.join(', ')} +${count} ${kind}${count > 1 ? 's' : ''} each`)
      open = false
    } catch (e) {
      error = e.message
    } finally {
      busy = false
    }
  }

  const field = $derived(kind === 'load' ? 'loads' : 'unloads')
  // loads happen at loading sites, unloads at unloading sites (untyped sites stay available)
  const fits = (x) => (kind === 'load' ? x.site_type !== 'unloading' : x.site_type !== 'loading')
  const siteOptions = $derived(registry.site.filter(fits))
  $effect(() => {
    const chosen = registry.site.find((x) => x.code === site)
    if (chosen && !fits(chosen)) site = ''
  })
  const preview = $derived(trucks.map((t) => {
    const before = perTruck[t]?.[field] || 0
    return { t, before, after: before + count }
  }))

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
    <Picker label="Trucks" options={registry.truck} bind:value={trucks} multi placeholder="Truck / reg. no." />
    <div class="row2">
      <div class="seg">
        <button type="button" class:on={kind === 'load'} onclick={() => (kind = 'load')}>+ Loads</button>
        <button type="button" class:on={kind === 'unload'} onclick={() => (kind = 'unload')}>+ Unloads</button>
      </div>
      <div class="stepper">
        <button type="button" class="btn quiet sm icon" onclick={() => (count = Math.max(1, count - 1))} aria-label="Less">−</button>
        <span class="mono">+{count}</span>
        <button type="button" class="btn quiet sm icon" onclick={() => (count = Math.min(50, count + 1))} aria-label="More">+</button>
      </div>
    </div>
    <Picker label="Site (optional)" options={siteOptions} bind:value={site} variant="labelled" />
    <input class="input" bind:value={note} placeholder="Note — optional" maxlength="120" />
    {#if me.is_admin}
      <label class="check"><input type="checkbox" checked={!postFleet} onchange={(e) => (postFleet = !e.target.checked)} /> Don't send to fleet group</label>
    {/if}
    {#if preview.length}
      <div class="preview">
        <span class="eyebrow">Adds {count} {field} to each</span>
        <p class="mono">{#each preview as p}<span><b>{p.t}</b> {p.before} → {p.after}</span>{/each}</p>
      </div>
    {/if}
    {#if error}<p class="notice err">{error}</p>{/if}
  </form>
  {#snippet actions()}
    <button class="btn ghost" onclick={() => (open = false)}>Cancel</button>
    <button class="btn signal" type="submit" form="manualform" disabled={!trucks.length || busy}>Add to summary</button>
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
  .stepper .mono { font-size: 18px; font-weight: 600; min-width: 34px; text-align: center; }
  .preview { display: flex; flex-direction: column; gap: 6px; padding: 10px 12px; border-radius: var(--r); background: var(--paper); box-shadow: inset 0 0 0 1px var(--hair-2); }
  .preview p { display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 13px; }
  @media (max-width: 520px) { li { grid-template-columns: 1fr auto; } li .mute { grid-column: 1; } }
</style>
