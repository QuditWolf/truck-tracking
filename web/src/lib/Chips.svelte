<script>
  // Tap-to-pick chips with a "+ other" entry for values not in the registry.
  let { options = [], value = $bindable(), multi = false, title = '', placeholder = 'Other' } = $props()

  let adding = $state(false)
  let custom = $state('')
  let extra = $state([]) // custom values typed this session

  const all = $derived([...options.map((o) => o.code), ...extra.filter((e) => !options.some((o) => o.code === e))])
  const labelOf = (code) => options.find((o) => o.code === code)?.label
  const selected = (code) => (multi ? value.includes(code) : value === code)

  function toggle(code) {
    if (multi) value = value.includes(code) ? value.filter((v) => v !== code) : [...value, code]
    else value = value === code ? '' : code
  }

  function addCustom() {
    const v = custom.trim()
    if (!v) return
    const known = options.find((o) => [o.code, o.label, ...(o.aliases || [])].some((x) => x.toLowerCase() === v.toLowerCase()))
    const code = known ? known.code : v
    if (!known && !extra.includes(code)) extra = [...extra, code]
    if (!selected(code)) toggle(code)
    custom = ''
    adding = false
  }
</script>

<section class="chips">
  {#if title}<h3>{title}</h3>{/if}
  <div class="row">
    {#each all as code (code)}
      <button type="button" class="chip" class:on={selected(code)} onclick={() => toggle(code)} title={labelOf(code)}>
        {code}
        {#if !labelOf(code)}<small>new</small>{/if}
      </button>
    {/each}
    {#if adding}
      <form class="custom" onsubmit={(e) => { e.preventDefault(); addCustom() }}>
        <!-- svelte-ignore a11y_autofocus -->
        <input bind:value={custom} {placeholder} autofocus onblur={addCustom} />
      </form>
    {:else}
      <button type="button" class="chip add" onclick={() => (adding = true)}>+</button>
    {/if}
  </div>
</section>
