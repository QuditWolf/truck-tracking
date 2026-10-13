<script>
  import { api } from '../lib/api.js'

  let { config, onLogin } = $props()
  let email = $state('')
  let error = $state('')
  let btn = $state()

  $effect(() => {
    if (!config.google_client_id || !btn) return
    const init = () => {
      window.google.accounts.id.initialize({
        client_id: config.google_client_id,
        callback: async ({ credential }) => {
          try { onLogin(await api.post('/api/auth/google', { credential })) } catch (e) { error = e.message }
        },
      })
      window.google.accounts.id.renderButton(btn, { theme: 'filled_black', size: 'large', shape: 'pill', text: 'continue_with' })
    }
    if (window.google?.accounts) init()
    else {
      const t = setInterval(() => { if (window.google?.accounts) { clearInterval(t); init() } }, 200)
      return () => clearInterval(t)
    }
  })

  async function dev(e) {
    e.preventDefault()
    try { onLogin(await api.post('/api/auth/dev', { email })) } catch (err) { error = err.message }
  }
</script>

<main class="center">
  <h1>Paddy 2026</h1>
  <p class="muted">Truck reporting</p>
  {#if config.google_client_id}<div bind:this={btn}></div>{/if}
  {#if config.dev_login}
    <form onsubmit={dev} class="stack">
      <input type="email" bind:value={email} placeholder="dev login email" required />
      <button>Dev login</button>
    </form>
  {/if}
  {#if error}<p class="error">{error}</p>{/if}
</main>
