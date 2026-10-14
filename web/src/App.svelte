<script>
  import { fade, fly } from 'svelte/transition'
  import Icon from './lib/Icon.svelte'
  import ShiftControl from './lib/ShiftControl.svelte'
  import { api } from './lib/api.js'
  import { toast, toasts } from './lib/stores.svelte.js'
  import Admin from './pages/Admin.svelte'
  import Fleet from './pages/Fleet.svelte'
  import Login from './pages/Login.svelte'
  import Mine from './pages/Mine.svelte'
  import Onboard from './pages/Onboard.svelte'
  import Report from './pages/Report.svelte'
  import Summary from './pages/Summary.svelte'
  import Supervisor from './pages/Supervisor.svelte'

  // /s/<token>: supervisor view, no login
  const supervisorToken = location.pathname.startsWith('/s/') ? location.pathname.slice(3).split('/')[0] : ''

  let config = $state(null)
  let me = $state(null)
  let registry = $state(null)
  let tick = $state(0) // bumps after any change so live views refetch
  let page = $state(location.hash.slice(1) || 'report')

  window.addEventListener('hashchange', () => (page = location.hash.slice(1) || 'report'))

  ;(async () => {
    config = await api.get('/api/config')
    try { me = await api.get('/api/me') } catch { me = null }
  })()

  async function refresh() {
    registry = await api.get('/api/registry')
    tick++
  }
  $effect(() => { if (me?.onboarded) refresh() })

  // Live: the server pushes a version number whenever anything changes (anyone, web or WhatsApp).
  let lastVersion = null
  let pending
  $effect(() => {
    if (!me?.onboarded) return
    const es = new EventSource('/api/live')
    es.onmessage = (e) => {
      if (lastVersion !== null && e.data !== lastVersion) {
        clearTimeout(pending)
        pending = setTimeout(refresh, 250) // coalesce bursts (multi-truck reports, imports)
      }
      lastVersion = e.data
    }
    return () => es.close()
  })

  async function logout() {
    await api.post('/api/auth/logout')
    me = null
    registry = null
  }

  // [route, title, icon, short tab label]
  const NAV = [
    ['report', 'Report', 'report', 'Report'],
    ['fleet', 'Fleet', 'truck', 'Fleet'],
    ['mine', 'Reports', 'mine', 'Reports'],
    ['summary', 'Summary', 'summary', 'Summary'],
  ]
  const nav = $derived(me?.is_admin ? [...NAV, ['admin', 'Admin', 'admin', 'Admin']] : NAV)
  const title = $derived(nav.find(([k]) => k === page)?.[1] || 'Report')
  const initials = $derived((me?.name || me?.email || '?').split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase())
</script>

{#if supervisorToken}
  <Supervisor token={supervisorToken} />
{:else if !config}
  <div class="splash"><span class="mark">DB</span></div>
{:else if !me}
  <Login {config} onLogin={(u) => (me = u)} />
{:else if !me.onboarded}
  <Onboard {me} onDone={(u) => (me = u)} />
{:else}
  <div class="app">
    <aside class="side">
      <a class="brand" href="#report"><span class="mark">DB</span><span class="name"><small>Dayalbagh</small>Truck Tracking</span></a>
      <nav>
        {#each nav as [k, label, icon]}
          <a href="#{k}" class:on={page === k}><Icon name={icon} size={17} />{label}</a>
        {/each}
      </nav>
      <div class="me">
        <span class="avatar">{initials}</span>
        <div class="who"><b>{me.name}</b><span>{me.email}</span></div>
        <button class="btn ghost sm icon" title="Sign out" onclick={logout}><Icon name="out" size={16} /></button>
      </div>
    </aside>

    <div class="main">
      <header class="top">
        <a class="brand compact" href="#report"><span class="mark">DB</span></a>
        <h1>{title}</h1>
        {#if registry}<ShiftControl shift={registry.shift} sites={registry.site} onChange={refresh} />{/if}
        <button class="avatar compact" title="Sign out {me.email}" onclick={logout}>{initials}</button>
      </header>

      <main class="view">
        {#if registry}
          {#key page}
            <div class="page" in:fly={{ y: 10, duration: 260, delay: 60 }} out:fade={{ duration: 60 }}>
              {#if page === 'report'}
                <Report {registry} {me} {tick} onChange={refresh} />
              {:else if page === 'fleet'}
                <Fleet {registry} {me} {tick} onChange={refresh} />
              {:else if page === 'mine'}
                <Mine {registry} {me} {tick} onChange={refresh} />
              {:else if page === 'summary'}
                <Summary {tick} {registry} {me} />
              {:else if page === 'admin' && me.is_admin}
                <Admin onChange={refresh} />
              {/if}
            </div>
          {/key}
        {/if}
      </main>
    </div>

    <nav class="tabs">
      {#each nav as [k, , icon, short]}
        <a href="#{k}" class:on={page === k}><Icon name={icon} size={20} /><span>{short}</span></a>
      {/each}
    </nav>
  </div>
{/if}

<div class="toasts">
  {#each toasts.list as t (t.id)}
    <div class="toast {t.kind}" in:fly={{ y: 16, duration: 220 }} out:fade={{ duration: 160 }}>
      <Icon name={t.kind === 'ok' ? 'check' : 'warn'} size={16} />{t.text}
    </div>
  {/each}
</div>

<style>
  .splash { height: 100dvh; display: grid; place-items: center; }
  .mark {
    display: inline-grid; place-items: center; width: 30px; height: 30px; border-radius: 8px;
    background: var(--ink); color: var(--paper); font: 700 11px/1 var(--mono); letter-spacing: -0.04em;
  }
  .splash .mark { animation: pulse 1.2s ease-in-out infinite; }

  .app { height: 100dvh; display: grid; grid-template-columns: var(--side-w) 1fr; }

  /* sidebar */
  .side {
    display: flex; flex-direction: column; gap: 22px; padding: 18px 14px; border-right: 1px solid var(--hair-2);
    background: var(--paper-2);
  }
  .brand { display: flex; align-items: center; gap: 10px; padding: 0 6px; text-decoration: none; color: var(--ink); font-weight: 650; letter-spacing: -0.02em; }
  .brand .name { display: flex; flex-direction: column; line-height: 1.15; }
  .brand .name small { font: 600 10px/1.2 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--mute); }
  .side nav { display: flex; flex-direction: column; gap: 2px; flex: 1; }
  .side nav a {
    display: flex; align-items: center; gap: 11px; height: 38px; padding: 0 10px; border-radius: 8px;
    color: var(--ink-2); text-decoration: none; font-weight: 520; transition: background .15s, color .15s;
  }
  .side nav a:hover { background: color-mix(in srgb, var(--surface) 70%, transparent); color: var(--ink); }
  .side nav a.on { background: var(--surface); color: var(--ink); box-shadow: var(--shadow); font-weight: 600; }
  .side nav a.on :global(svg) { color: var(--signal); }
  .me { display: flex; align-items: center; gap: 10px; padding: 10px 6px 0; border-top: 1px solid var(--hair); }
  .avatar {
    display: grid; place-items: center; width: 32px; height: 32px; border-radius: 50%; flex-shrink: 0;
    background: var(--surface); box-shadow: inset 0 0 0 1px var(--hair); font: 600 11px/1 var(--mono); color: var(--ink-2);
  }
  .who { display: flex; flex-direction: column; min-width: 0; flex: 1; font-size: 13px; line-height: 1.25; }
  .who span { color: var(--mute); font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  /* main column */
  .main { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
  .top {
    height: var(--top-h); flex-shrink: 0; display: flex; align-items: center; gap: 12px;
    padding: 0 var(--pad); border-bottom: 1px solid var(--hair-2);
    background: color-mix(in srgb, var(--paper) 85%, transparent); backdrop-filter: blur(10px);
  }
  .top h1 { font-size: 17px; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .compact { display: none; }
  .view { flex: 1; min-height: 0; overflow-y: auto; overflow-x: hidden; scroll-behavior: smooth; }
  .page { min-height: 100%; padding: 20px var(--pad) 0; display: flex; flex-direction: column; }

  .tabs { display: none; }

  :global(:root) { --pad: 28px; }

  @media (max-width: 860px) {
    :global(:root) { --pad: 16px; }
    .app { grid-template-columns: 1fr; grid-template-rows: 1fr auto; }
    .side { display: none; }
    .compact { display: inline-grid; }
    .brand.compact { padding: 0; margin-right: auto; flex-shrink: 0; }
    .top { gap: 8px; }
    .top :global(.shift) { flex-shrink: 1; }
    .avatar.compact { flex-shrink: 0; }
    .top h1 { display: none; }
    .page { padding-top: 14px; }
    .tabs {
      display: grid; grid-auto-flow: column; grid-auto-columns: 1fr;
      height: calc(var(--nav-h) + var(--safe-b)); padding-bottom: var(--safe-b);
      background: var(--surface); border-top: 1px solid var(--hair-2);
    }
    .tabs a {
      display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px;
      color: var(--mute); text-decoration: none; font-size: 11px; font-weight: 550; position: relative;
      transition: color .15s;
    }
    .tabs a.on { color: var(--ink); }
    .tabs a.on::before {
      content: ''; position: absolute; top: 0; left: 30%; right: 30%; height: 2px; border-radius: 0 0 2px 2px; background: var(--signal);
    }
  }
  @media (max-width: 420px) {
    .top h1 { font-size: 15.5px; }
  }

  .toasts {
    position: fixed; z-index: 50; left: 50%; translate: -50% 0; bottom: calc(24px + var(--safe-b));
    display: flex; flex-direction: column; gap: 8px; align-items: center; pointer-events: none;
  }
  @media (max-width: 860px) { .toasts { bottom: calc(var(--nav-h) + 16px + var(--safe-b)); } }
  .toast {
    display: flex; align-items: center; gap: 8px; padding: 10px 14px 10px 12px; border-radius: 12px;
    background: var(--ink); color: var(--paper); font-size: 13.5px; font-weight: 550; box-shadow: var(--shadow-lift);
    white-space: nowrap;
  }
  .toast :global(svg) { color: #8fd19e; }
  .toast.warn :global(svg) { color: var(--signal); }
</style>
