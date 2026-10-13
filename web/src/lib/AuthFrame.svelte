<script>
  let { children } = $props()
  // decorative: what the log looks like in use
  const LINES = [
    ['06:12', 'D', 'ENTER', 'SOC'], ['06:18', 'D', 'LS', 'SOC'], ['06:31', 'A,B', 'LS', 'KN4'], ['06:52', 'D', 'LO', 'SOC'],
    ['07:05', 'F', 'US', 'DAIRY'], ['07:14', 'A', 'LO', 'KN4'], ['07:20', 'F', 'UO', 'DAIRY'], ['07:41', 'D', 'US', 'DAIRY'],
    ['07:58', 'B', 'LO', 'KN4'], ['08:06', 'D', 'UO', 'DAIRY'], ['08:22', 'E', 'LS', 'LG'], ['08:40', 'A', 'US', 'DAIRY'],
  ]
</script>

<div class="frame">
  <aside class="panel">
    <div class="brand"><span class="mark">TT</span>Truck tracking</div>
    <div class="log" aria-hidden="true">
      <div class="scroll">
        {#each [...LINES, ...LINES] as [t, tr, v, s]}
          <p><span class="t">{t}</span><span>{tr}</span><span class="v">{v}</span><span>{s}</span></p>
        {/each}
      </div>
    </div>
    <div class="claim">
      <h1>Every trolley,<br />accounted for.</h1>
      <p>One tap per event. Counts, gaps and duplicates sorted out for you.</p>
    </div>
  </aside>
  <main class="content">
    <div class="inner rise">{@render children()}</div>
  </main>
</div>

<style>
  .frame { min-height: 100dvh; display: grid; grid-template-columns: minmax(0, 1fr) minmax(380px, 520px); }
  .panel {
    position: relative; overflow: hidden; background: var(--ink); color: var(--paper);
    display: flex; flex-direction: column; justify-content: space-between; padding: 36px 44px;
  }
  .brand { display: flex; align-items: center; gap: 10px; font-weight: 650; letter-spacing: -0.02em; position: relative; z-index: 1; }
  .mark { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 8px; background: var(--signal); color: #fff; font: 700 11px/1 var(--mono); }
  .log {
    position: absolute; inset: 0; padding: 0 44px; display: flex; justify-content: flex-end;
    mask-image: linear-gradient(to bottom, transparent, #000 25%, #000 55%, transparent 85%);
  }
  .scroll { animation: roll 36s linear infinite; padding-top: 40px; }
  .log p { display: grid; grid-template-columns: 70px 56px 84px 80px; font: 500 15px/2.4 var(--mono); color: rgba(243, 241, 236, .38); letter-spacing: -0.02em; }
  .log .t { color: rgba(243, 241, 236, .22); }
  .log .v { color: color-mix(in srgb, var(--signal) 75%, transparent); }
  @keyframes roll { to { transform: translateY(-50%); } }
  .claim { position: relative; z-index: 1; max-width: 460px; }
  .claim h1 { font-size: clamp(34px, 4vw, 52px); line-height: 1.02; letter-spacing: -0.045em; font-weight: 650; }
  .claim p { margin-top: 14px; color: rgba(243, 241, 236, .62); font-size: 15.5px; }

  .content { display: grid; place-items: center; padding: 40px 28px; }
  .inner { width: 100%; max-width: 360px; display: flex; flex-direction: column; gap: 20px; }

  @media (max-width: 860px) {
    .frame { grid-template-columns: 1fr; grid-template-rows: auto 1fr; }
    .panel { min-height: 34vh; padding: 24px 22px; }
    .log { padding: 0 22px; mask-image: linear-gradient(to bottom, transparent, #000 20%, #000 35%, transparent 60%); opacity: .7; }
    .log p { font-size: 12.5px; grid-template-columns: 54px 44px 64px 60px; }
    .claim h1 { font-size: 30px; }
    .claim p { display: none; }
    .content { place-items: start center; padding: 28px 22px; }
  }
</style>
