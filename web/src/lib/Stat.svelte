<script>
  import { Tween } from 'svelte/motion'
  import { cubicOut } from 'svelte/easing'

  let { label, value = 0, sub = '', accent = false, warn = false } = $props()
  const n = new Tween(0, { duration: 700, easing: cubicOut })
  $effect(() => { n.target = value })
</script>

<div class="stat" class:accent class:warn>
  <span class="eyebrow">{label}</span>
  <b class="mono">{Math.round(n.current)}</b>
  <span class="sub">{sub}</span>
</div>

<style>
  .stat {
    position: relative; display: flex; flex-direction: column; gap: 6px; padding: 16px 18px 14px;
    background: var(--surface); border-radius: var(--r-lg); box-shadow: inset 0 0 0 1px var(--hair-2), var(--shadow); overflow: hidden;
  }
  b { font-size: clamp(30px, 4vw, 44px); line-height: 1; font-weight: 600; letter-spacing: -0.06em; }
  .sub { font-size: 12.5px; color: var(--mute); }
  .accent::before { content: ''; position: absolute; inset: 0 auto 0 0; width: 3px; background: var(--signal); }
  .warn b { color: var(--amber); }
</style>
