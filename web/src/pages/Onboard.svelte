<script>
  import { untrack } from 'svelte'
  import { api } from '../lib/api.js'

  let { me, onDone } = $props()
  let name = $state(untrack(() => me.name) || '')
  let phone = $state(untrack(() => me.phone) || '')
  let error = $state('')

  async function save(e) {
    e.preventDefault()
    try { onDone(await api.put('/api/me', { name, phone })) } catch (err) { error = err.message }
  }
</script>

<main class="center">
  <h1>Welcome</h1>
  <p class="muted">{me.email}</p>
  <form onsubmit={save} class="stack">
    <label>Name <small class="muted">shown on WhatsApp</small>
      <input bind:value={name} required autocomplete="given-name" />
    </label>
    <label>Phone
      <input bind:value={phone} type="tel" required placeholder="+91 98765 43210" autocomplete="tel" />
    </label>
    <button>Continue</button>
  </form>
  {#if error}<p class="error">{error}</p>{/if}
</main>
