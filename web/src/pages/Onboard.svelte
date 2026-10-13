<script>
  import { untrack } from 'svelte'
  import AuthFrame from '../lib/AuthFrame.svelte'
  import { api } from '../lib/api.js'

  let { me, onDone } = $props()
  let name = $state(untrack(() => me.name) || '')
  let phone = $state(untrack(() => me.phone) || '')
  let error = $state('')
  let busy = $state(false)

  async function save(e) {
    e.preventDefault()
    busy = true
    try { onDone(await api.put('/api/me', { name, phone })) } catch (err) { error = err.message } finally { busy = false }
  }
</script>

<AuthFrame>
  <div class="head">
    <span class="eyebrow">{me.email}</span>
    <h2>Your details</h2>
    <p class="mute">Your first name is shown with each report you send, here and on WhatsApp.</p>
  </div>
  <form onsubmit={save} class="form">
    <label class="field"><span>Name</span><input class="input" bind:value={name} required autocomplete="given-name" placeholder="Ravi" /></label>
    <label class="field"><span>Phone</span><input class="input mono" bind:value={phone} type="tel" required placeholder="+91 98765 43210" autocomplete="tel" /></label>
    {#if error}<p class="notice err">{error}</p>{/if}
    <button class="btn signal" disabled={busy}>Continue</button>
  </form>
</AuthFrame>

<style>
  .head { display: flex; flex-direction: column; gap: 6px; }
  h2 { font-size: 17px; }
  .head p { font-size: 13.5px; }
  .form { display: flex; flex-direction: column; gap: 14px; }
  .form .btn { height: 46px; }
</style>
