<script>
  import { api, line } from './lib/api.js'
  import ReportForm from './lib/ReportForm.svelte'
  import ReportList from './lib/ReportList.svelte'
  import ShiftBar from './lib/ShiftBar.svelte'
  import Admin from './pages/Admin.svelte'
  import Login from './pages/Login.svelte'
  import Onboard from './pages/Onboard.svelte'
  import Summary from './pages/Summary.svelte'

  let config = $state(null)
  let me = $state(null)
  let registry = $state(null)
  let page = $state(location.hash.slice(1) || 'report')
  let mine = $state([])
  let feed = $state([])
  let toast = $state('')

  window.addEventListener('hashchange', () => (page = location.hash.slice(1) || 'report'))

  async function boot() {
    config = await api.get('/api/config')
    try { me = await api.get('/api/me') } catch { me = null }
  }
  boot()

  async function refresh() {
    registry = await api.get('/api/registry')
    if (page === 'mine') mine = await api.get('/api/reports')
    if (page === 'feed') feed = await api.get('/api/feed')
  }
  $effect(() => { if (me?.onboarded) { page; refresh() } })

  function sent(r) {
    toast = `Sent: ${line(r)}`
    setTimeout(() => (toast = ''), 3000)
    refresh()
  }

  async function logout() {
    await api.post('/api/auth/logout')
    me = null
  }

  const tabs = $derived([['report', 'Report'], ['mine', 'Mine'], ['feed', 'All'], ['summary', 'Summary'],
    ...(me?.is_admin ? [['admin', 'Admin']] : [])])
</script>

{#if !config}
  <main class="center muted">Loading…</main>
{:else if !me}
  <Login {config} onLogin={(u) => (me = u)} />
{:else if !me.onboarded}
  <Onboard {me} onDone={(u) => (me = u)} />
{:else}
  <header>
    <nav>
      {#each tabs as [k, label]}<a href="#{k}" class:on={page === k}>{label}</a>{/each}
    </nav>
    <button class="small ghost" onclick={logout} title={me.email}>{me.name} ⎋</button>
  </header>
  <main>
    {#if registry}
      {#if page === 'report'}
        <ShiftBar shift={registry.shift} sites={registry.site} onChange={refresh} />
        {#key registry.shift?.id}
          <ReportForm {registry} onDone={sent} />
        {/key}
      {:else if page === 'mine'}
        <ReportList items={mine} {registry} {me} onChange={refresh} />
      {:else if page === 'feed'}
        <ReportList items={feed} {registry} {me} onChange={refresh} showUser />
      {:else if page === 'summary'}
        <Summary />
      {:else if page === 'admin' && me.is_admin}
        <Admin />
      {/if}
    {/if}
  </main>
  {#if toast}<div class="toast">{toast}</div>{/if}
{/if}
