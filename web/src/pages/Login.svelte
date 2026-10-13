<script>
  import AuthFrame from '../lib/AuthFrame.svelte'
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
      window.google.accounts.id.renderButton(btn, { theme: 'outline', size: 'large', shape: 'rectangular', text: 'continue_with', width: 320 })
    }
    if (window.google?.accounts) init()
    else {
      const t = setInterval(() => { if (window.google?.accounts) { clearInterval(t); init() } }, 150)
      return () => clearInterval(t)
    }
  })

  async function dev(e) {
    e.preventDefault()
    try { onLogin(await api.post('/api/auth/dev', { email })) } catch (err) { error = err.message }
  }
</script>

<AuthFrame>
  <div class="head">
    <h2>Sign in</h2>
    <p class="mute">Use your Google account. First time? You'll add your name and phone next.</p>
  </div>
  {#if config.google_client_id}<div class="gbtn" bind:this={btn}></div>{/if}
  {#if config.dev_login}
    <form onsubmit={dev} class="dev">
      <span class="eyebrow">Development login</span>
      <input class="input" type="email" bind:value={email} placeholder="you@example.com" required />
      <button class="btn">Continue</button>
    </form>
  {/if}
  {#if error}<p class="notice err">{error}</p>{/if}
</AuthFrame>

<style>
  .head { display: flex; flex-direction: column; gap: 6px; }
  h2 { font-size: 26px; letter-spacing: -0.035em; }
  .gbtn { min-height: 44px; }
  .dev { display: flex; flex-direction: column; gap: 10px; padding-top: 18px; border-top: 1px solid var(--hair); }
  .dev .btn { height: 44px; }
</style>
