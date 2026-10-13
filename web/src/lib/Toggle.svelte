<script>
  let { checked = false, label = '', hint = '', disabled = false, onchange } = $props()
</script>

<label class="toggle" class:disabled>
  <span class="text">
    <b>{label}</b>
    {#if hint}<span>{hint}</span>{/if}
  </span>
  <input type="checkbox" {checked} {disabled} onchange={(e) => onchange?.(e.target.checked)} />
  <span class="switch" aria-hidden="true"></span>
</label>

<style>
  .toggle { display: flex; align-items: center; gap: 14px; padding: 12px 0; cursor: pointer; border-top: 1px solid var(--hair-2); }
  .toggle:first-child { border-top: 0; }
  .text { flex: 1; display: flex; flex-direction: column; gap: 2px; }
  .text b { font-weight: 600; font-size: 14px; }
  .text span { font-size: 12.5px; color: var(--mute); }
  input { position: absolute; opacity: 0; pointer-events: none; }
  .switch {
    position: relative; flex-shrink: 0; width: 40px; height: 24px; border-radius: 99px; background: var(--hair);
    transition: background .2s var(--ease);
  }
  .switch::after {
    content: ''; position: absolute; top: 3px; left: 3px; width: 18px; height: 18px; border-radius: 50%;
    background: #fff; box-shadow: 0 1px 3px rgba(0, 0, 0, .2); transition: transform .22s var(--ease);
  }
  input:checked + .switch { background: var(--ink); }
  input:checked + .switch::after { transform: translateX(16px); }
  input:focus-visible + .switch { outline: 2px solid var(--signal); outline-offset: 2px; }
  .disabled { opacity: .45; cursor: default; }
</style>
