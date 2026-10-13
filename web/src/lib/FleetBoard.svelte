<script>
  import { onDestroy } from 'svelte'
  import { api, time } from './api.js'

  // tick: bump to force a refresh (after a send)
  let { tick = 0, columns = 'auto' } = $props()

  let board = $state(null)
  async function load() {
    try { board = await api.get('/api/board') } catch { /* keep last */ }
  }
  $effect(() => { tick; load() })
  const timer = setInterval(load, 20000)
  onDestroy(() => clearInterval(timer))

  const ORDER = ['loading', 'loaded', 'unloading', 'empty', 'done', 'idle']
  const LABEL = { loading: 'Loading', loaded: 'Loaded', unloading: 'Unloading', empty: 'Empty', done: 'Done', idle: 'Idle' }
  const counts = $derived(
    board ? ORDER.map((k) => [k, board.trucks.filter((t) => t.position === k).length]).filter(([, n]) => n) : [],
  )
</script>

<section class="board">
  <header>
    <div>
      <span class="eyebrow">Fleet</span>
      <h3>{board?.shift || 'No shift yet'}</h3>
    </div>
    {#if board?.open}<span class="pill live">Live</span>{/if}
  </header>

  {#if board}
    <div class="legend">
      {#each counts as [k, n]}<span class="pill {k}">{n} {LABEL[k]}</span>{/each}
    </div>
    <div class="grid" style:--cols={columns}>
      {#each board.trucks as t (t.truck)}
        <div class="truck {t.position}">
          <div class="top">
            <span class="code">{t.truck}</span>
            <span class="dot" title={LABEL[t.position]}></span>
          </div>
          {#if t.last}
            <p class="last mono">{t.last.verb}{t.last.site ? ` ${t.last.site}` : ''}</p>
            <p class="meta">{time(t.last.time)}{t.last.user ? ` · ${t.last.user}` : ''}</p>
          {:else}
            <p class="meta">No reports</p>
          {/if}
          {#if t.loads}<span class="loads mono" title="Loads this shift">{t.loads}</span>{/if}
        </div>
      {:else}
        <p class="mute">No trucks yet — add them in Admin.</p>
      {/each}
    </div>
  {:else}
    <div class="grid skeleton">{#each Array(8) as _}<div class="truck"></div>{/each}</div>
  {/if}
</section>

<style>
  .board { display: flex; flex-direction: column; gap: 14px; }
  header { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; }
  header h3 { font-size: 17px; margin-top: 6px; }
  .legend { display: flex; flex-wrap: wrap; gap: 6px; }
  .grid { display: grid; gap: 8px; grid-template-columns: repeat(auto-fill, minmax(118px, 1fr)); }

  .truck {
    --c: var(--mute); --bg: var(--surface);
    position: relative; min-height: 96px; padding: 12px; border-radius: var(--r-lg);
    background: var(--bg); box-shadow: inset 0 0 0 1px var(--hair-2), var(--shadow);
    display: flex; flex-direction: column; gap: 3px; overflow: hidden;
    transition: background .4s var(--ease), box-shadow .3s;
  }
  .truck::after { content: ''; position: absolute; left: 0; top: 12px; bottom: 12px; width: 3px; border-radius: 0 3px 3px 0; background: var(--c); }
  .truck.loading { --c: var(--amber); }
  .truck.loaded { --c: var(--blue); }
  .truck.unloading { --c: var(--plum); }
  .truck.empty, .truck.done { --c: var(--moss); }
  .truck.idle { --bg: transparent; box-shadow: inset 0 0 0 1px var(--hair-2); }
  .truck.idle::after { display: none; }

  .top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
  .code { font: 650 22px/1 var(--mono); letter-spacing: -0.05em; }
  .idle .code { color: var(--mute); }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--c); }
  .last { font-size: 12.5px; font-weight: 600; }
  .meta { font-size: 12px; color: var(--mute); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .loads {
    position: absolute; right: 10px; bottom: 10px; font-size: 10.5px; font-weight: 600;
    padding: 3px 6px; border-radius: 6px; background: var(--paper-2); color: var(--ink-2);
  }
  @media (max-width: 520px) { .grid { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; } .truck { min-height: 84px; padding: 10px; } .code { font-size: 19px; } }
  .skeleton .truck { animation: pulse 1.4s ease-in-out infinite; }
  .skeleton .truck::after { display: none; }
</style>
