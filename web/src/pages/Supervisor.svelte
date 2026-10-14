<script>
  // No-login view behind an unguessable link: current shift summary and fleet board, auto-refreshing.
  import { onDestroy } from 'svelte'
  import FleetBoard from '../lib/FleetBoard.svelte'
  import Icon from '../lib/Icon.svelte'
  import Stat from '../lib/Stat.svelte'
  import { api, time } from '../lib/api.js'
  import { toast } from '../lib/stores.svelte.js'  // toasts render in App

  let { token } = $props()
  let data = $state(null)
  let error = $state('')
  let tick = $state(0)
  let updated = $state(null)

  async function load() {
    try {
      data = await api.get(`/api/public/${token}/summary`)
      error = ''
      updated = new Date().toISOString()
      tick++
    } catch (e) {
      error = e.status === 404 ? 'This link is no longer valid. Ask an admin for the current one.' : e.message
    }
  }
  load()
  const timer = setInterval(load, 20000)
  onDestroy(() => clearInterval(timer))

  const c = $derived(data?.counts)
  async function copy() {
    try { await navigator.clipboard.writeText(data.text); toast('Summary copied') } catch { toast('Long-press the text to copy', 'warn') }
  }
  async function share() {
    if (navigator.share) { try { await navigator.share({ text: data.text }) } catch { /* dismissed */ } }
    else window.open(`https://wa.me/?text=${encodeURIComponent(data.text)}`, '_blank', 'noopener')
  }
</script>

<div class="sup">
  <header>
    <div class="brand"><span class="mark">DB</span><span class="name"><small>Dayalbagh</small>Truck Tracking</span></div>
    {#if data?.open}<span class="pill live">Live</span>{/if}
  </header>

  {#if error}
    <div class="empty-state"><Icon name="warn" size={22} /><p>{error}</p></div>
  {:else if data}
    <main>
      <div class="head">
        <h1>{data.title || 'No shift yet'}</h1>
        {#if updated}<span class="mute small">Updated {time(updated)}</span>{/if}
      </div>
      {#if c}
        <div class="stats">
          <Stat label="Loaded" value={c.loaded} sub="this shift" accent />
          <Stat label="Unloaded" value={c.unloaded} sub="this shift" />
        </div>
      {/if}
      <div class="grid">
        <section class="card">
          <div class="card-h"><h3>Summary</h3>
            <span class="row"><button class="btn quiet sm" onclick={copy}><Icon name="copy" size={14} />Copy</button>
              <button class="btn signal sm" onclick={share}><Icon name="send" size={14} />Share</button></span></div>
          <div class="card-b"><pre class="mono">{data.text}</pre></div>
        </section>
        <section class="card"><div class="card-b board"><FleetBoard {tick} src={`/api/public/${token}/board`} /></div></section>
      </div>
    </main>
  {/if}
</div>


<style>
  .sup { min-height: 100dvh; }
  header { display: flex; justify-content: space-between; align-items: center; padding: 14px 20px; border-bottom: 1px solid var(--hair-2); }
  .brand { display: flex; align-items: center; gap: 10px; font-weight: 650; }
  .mark { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 8px; background: var(--ink); color: var(--paper); font: 700 11px/1 var(--mono); }
  .name { display: flex; flex-direction: column; line-height: 1.15; }
  .name small { font: 600 10px/1.2 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--mute); }
  main { max-width: 1200px; margin: 0 auto; padding: 20px; display: flex; flex-direction: column; gap: 16px; }
  .head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
  h1 { font-size: 20px; }
  .small { font-size: 12.5px; }
  .stats { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr); gap: 12px; align-items: start; }
  .row { display: flex; gap: 6px; }
  pre { margin: 0; padding: 14px 16px; border-radius: var(--r); background: var(--paper); box-shadow: inset 0 0 0 1px var(--hair-2);
        font-size: 13px; line-height: 1.65; white-space: pre-wrap; }
  .board { padding-top: 16px; }
  @media (max-width: 860px) { .grid { grid-template-columns: minmax(0, 1fr); } main { padding: 14px; } }
</style>
