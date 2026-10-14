<script>
  // Admin: supervisor link (no login) and read-only API keys.
  import Icon from '../lib/Icon.svelte'
  import Modal from '../lib/Modal.svelte'
  import { api, dateTime } from '../lib/api.js'
  import { toast } from '../lib/stores.svelte.js'

  let token = $state(null)
  let keys = $state([])
  let newName = $state('')
  let created = $state(null) // { name, key } shown once
  let createdOpen = $state(false)

  async function load() {
    token = (await api.get('/api/admin/supervisor')).token
    keys = await api.get('/api/admin/keys')
  }
  load()

  const link = $derived(token ? `${location.origin}/s/${token}` : '')
  async function copy(text, msg) {
    try { await navigator.clipboard.writeText(text); toast(msg) } catch { toast('Select and copy the text', 'warn') }
  }
  async function newLink() {
    if (token && !confirm('Make a new link? The current link stops working.')) return
    token = (await api.post('/api/admin/supervisor')).token
    toast('New supervisor link ready')
  }
  async function disable() {
    if (!confirm('Turn off the supervisor link?')) return
    token = (await api.del('/api/admin/supervisor')).token
    toast('Supervisor link off')
  }
  async function createKey(e) {
    e.preventDefault()
    created = await api.post('/api/admin/keys', { name: newName })
    createdOpen = true
    newName = ''
    load()
  }
  async function revoke(k) {
    if (!confirm(`Revoke "${k.name}"? Anything using it stops working.`)) return
    await api.del(`/api/admin/keys/${k.id}`)
    toast('Key revoked')
    load()
  }
</script>

<div class="access">
  <section class="card">
    <div class="card-h"><div><h3>Supervisor link</h3><span class="mute small">Current shift summary and fleet board, no sign-in. Anyone with the link can view.</span></div></div>
    <div class="card-b">
      {#if token}
        <div class="row link"><code class="mono">{link}</code></div>
        <div class="row">
          <button class="btn quiet sm" onclick={() => copy(link, 'Link copied')}><Icon name="copy" size={14} />Copy</button>
          <a class="btn quiet sm" href={link} target="_blank" rel="noopener">Open</a>
          <button class="btn quiet sm" onclick={newLink}>New link</button>
          <button class="btn ghost sm danger" onclick={disable}>Turn off</button>
        </div>
      {:else if token !== null}
        <p class="mute small">Off.</p>
        <button class="btn signal sm" onclick={newLink}>Create link</button>
      {/if}
    </div>
  </section>

  <section class="card">
    <div class="card-h"><div><h3>API keys</h3><span class="mute small">Read-only access to <code>/api/v1/…</code> for scripts and other apps. Keys can't change anything.</span></div></div>
    <form class="card-b row" onsubmit={createKey}>
      <input class="input sm grow" bind:value={newName} placeholder="Name (e.g. reporting sheet)" required />
      <button class="btn signal sm"><Icon name="plus" size={14} />Create key</button>
    </form>
    <div class="table-wrap">
      <table class="table">
        <thead><tr><th>Name</th><th>Key</th><th>Created</th><th>Last used</th><th></th></tr></thead>
        <tbody>
          {#each keys as k (k.id)}
            <tr class:inactive={k.revoked}>
              <td class="strong">{k.name}</td><td class="mono small">{k.prefix}…</td>
              <td class="small">{dateTime(k.created_at)}{k.by ? ` · ${k.by}` : ''}</td>
              <td class="small">{k.last_used_at ? dateTime(k.last_used_at) : 'never'}</td>
              <td class="num">{#if k.revoked}<span class="pill idle plain">revoked</span>{:else}<button class="btn ghost sm danger" onclick={() => revoke(k)}>Revoke</button>{/if}</td>
            </tr>
          {:else}
            <tr><td colspan="5" class="mute">No keys yet.</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
    <div class="card-b usage">
      <span class="eyebrow">Usage</span>
      <pre class="mono">curl -H "Authorization: Bearer tt_…" {location.origin}/api/v1/summary/shift
GET /api/v1/summary/shift[?shift_id=]   /api/v1/summary/range?start=YYYY-MM-DD&amp;end=…
GET /api/v1/reports[?since=&amp;until=&amp;limit=]   /api/v1/shifts   /api/v1/board   /api/v1/registry</pre>
    </div>
  </section>
</div>

<Modal bind:open={createdOpen} title="New API key">
  {#if created}
    <p>Copy it now — it won't be shown again.</p>
    <code class="mono key">{created.key}</code>
  {/if}
  {#snippet actions()}
    <button class="btn signal" onclick={() => { copy(created.key, 'Key copied'); createdOpen = false }}>Copy and close</button>
  {/snippet}
</Modal>

<style>
  .access { display: flex; flex-direction: column; gap: 12px; max-width: 900px; }
  .card-h > div { display: flex; flex-direction: column; gap: 3px; }
  .small { font-size: 12.5px; }
  .strong { font-weight: 600; }
  .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .row + .row { margin-top: 10px; }
  .link code, .key { display: block; padding: 10px 12px; border-radius: var(--r); background: var(--paper); box-shadow: inset 0 0 0 1px var(--hair-2); font-size: 12.5px; word-break: break-all; width: 100%; }
  .usage pre { margin: 6px 0 0; padding: 10px 12px; border-radius: var(--r); background: var(--paper); font-size: 11.5px; white-space: pre-wrap; }
  .inactive { opacity: .5; }
</style>
