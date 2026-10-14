<script>
  import { flip } from 'svelte/animate'
  // Tile picker with an "other" tile for values not in the registry.
  let { options = [], value = $bindable(), multi = false, label = '', variant = 'code', placeholder = 'Other…' } = $props()

  let adding = $state(false)
  let custom = $state('')
  let extra = $state([])

  const tiles = $derived([
    ...options.map((o) => ({ code: o.code, sub: variant === 'code' ? '' : o.label !== o.code ? o.label : '', title: [o.label, o.plate].filter(Boolean).join(' · ') })),
    ...extra.filter((e) => !options.some((o) => o.code === e)).map((code) => ({ code, sub: 'new', isNew: true })),
  ])
  // Long codes (e.g. registration numbers) take 2–3 grid columns instead of overflowing.
  const span = (code) => {
    const n = code.length
    return variant === 'code' ? (n <= 4 ? 1 : n <= 8 ? 2 : 3) : (n <= 9 ? 1 : 2)
  }
  const isOn = (code) => (multi ? value.includes(code) : value === code)
  const count = $derived(multi ? value.length : value ? 1 : 0)

  function toggle(code) {
    if (multi) value = value.includes(code) ? value.filter((v) => v !== code) : [...value, code]
    else value = value === code ? '' : code
  }

  function commit() {
    const v = custom.trim()
    adding = false
    custom = ''
    if (!v) return
    const known = options.find((o) => [o.code, o.label, ...(o.aliases || [])].some((x) => x.toLowerCase() === v.toLowerCase()))
    const code = known ? known.code : v
    if (!known && !extra.includes(code)) extra = [...extra, code]
    if (!isOn(code)) toggle(code)
  }

  function focus(node) { node.focus() }
</script>

<section class="picker">
  <header>
    <span class="eyebrow">{label}</span>
    {#if multi && count}<button type="button" class="clear" onclick={() => (value = [])}>{count} selected · clear</button>{/if}
  </header>
  <div class="tiles {variant}">
    {#each tiles as t (t.code)}
      <button type="button" class="tile" class:on={isOn(t.code)} class:new={t.isNew} class:long={t.code.length > 8}
              title={t.title} style:grid-column="span {span(t.code)}" onclick={() => toggle(t.code)}
              animate:flip={{ duration: 320 }}>
        <span class="code">{t.code}</span>
        {#if t.sub}<span class="sub">{t.sub}</span>{/if}
      </button>
    {/each}
    {#if adding}
      <form class="tile input-tile" onsubmit={(e) => { e.preventDefault(); commit() }}>
        <input use:focus bind:value={custom} {placeholder} onblur={commit} onkeydown={(e) => e.key === 'Escape' && ((custom = ''), commit())} />
      </form>
    {:else}
      <button type="button" class="tile add" onclick={() => (adding = true)} aria-label="Add other">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
      </button>
    {/if}
  </div>
</section>

<style>
  .picker { display: flex; flex-direction: column; gap: 10px; }
  header { display: flex; justify-content: space-between; align-items: baseline; min-height: 16px; }
  .clear { font-size: 12px; color: var(--mute); }
  .clear:hover { color: var(--ink); }

  .tiles { display: grid; gap: 6px; grid-auto-flow: row dense; grid-template-columns: repeat(auto-fill, minmax(var(--tile-min, 54px), 1fr)); }
  .tiles.code { --tile-min: 54px; }
  .tiles.labelled { --tile-min: 104px; }

  .tile {
    position: relative; min-height: 54px; padding: 8px 6px; border-radius: var(--r);
    display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 3px;
    background: var(--surface); box-shadow: inset 0 0 0 1px var(--hair), var(--shadow);
    transition: background .18s var(--ease), color .18s, box-shadow .18s, transform .1s var(--ease);
  }
  .tile:hover { box-shadow: inset 0 0 0 1px var(--ink-2), var(--shadow); }
  .tile:active { transform: scale(.95); }
  .tile.on { background: var(--ink); color: var(--paper); box-shadow: inset 0 0 0 1px var(--ink), 0 6px 14px -8px rgba(22, 24, 27, .6); }
  .code { font: 600 15px/1.1 var(--mono); letter-spacing: -0.03em; max-width: 100%; overflow-wrap: anywhere; text-align: center; }
  .tile.long .code { font-size: 13px; }
  .sub {
    font-size: 11px; line-height: 1.15; color: var(--mute); text-align: center;
    overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  }
  .tile.on .sub { color: color-mix(in srgb, var(--paper) 65%, transparent); }
  .tile.new .sub { color: var(--signal); font: 600 9.5px/1 var(--mono); text-transform: uppercase; letter-spacing: .06em; }
  .tile.add { color: var(--mute); box-shadow: inset 0 0 0 1px var(--hair); background: transparent; border: 1px dashed transparent; }
  .tile.add:hover { color: var(--ink); }
  .input-tile { grid-column: span 2; padding: 0; box-shadow: inset 0 0 0 1.5px var(--ink); }
  .input-tile input {
    width: 100%; height: 100%; min-height: 54px; border: 0; outline: 0; background: transparent;
    padding: 0 12px; font: 600 14px var(--mono); letter-spacing: -0.02em;
  }
</style>
