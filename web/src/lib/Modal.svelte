<script>
  import { fade, fly } from 'svelte/transition'

  let { open = $bindable(false), title = '', children, actions } = $props()
</script>

<svelte:window onkeydown={(e) => open && e.key === 'Escape' && (open = false)} />

{#if open}
  <div class="scrim" transition:fade={{ duration: 150 }} onclick={() => (open = false)} role="presentation"></div>
  <div class="sheet" role="dialog" aria-modal="true" aria-label={title} transition:fly={{ y: 24, duration: 260, opacity: 0 }}>
    {#if title}<h3>{title}</h3>{/if}
    <div class="body">{@render children?.()}</div>
    {#if actions}<div class="actions">{@render actions()}</div>{/if}
  </div>
{/if}

<style>
  .scrim { position: fixed; inset: 0; z-index: 40; background: rgba(22, 24, 27, .32); backdrop-filter: blur(2px); }
  .sheet {
    position: fixed; z-index: 41; left: 50%; top: 50%; translate: -50% -50%;
    width: min(440px, calc(100vw - 24px)); padding: 22px; border-radius: 18px;
    background: var(--surface); box-shadow: var(--shadow-lift);
    display: flex; flex-direction: column; gap: 14px;
  }
  h3 { font-size: 17px; }
  .body { color: var(--ink-2); font-size: 14.5px; display: flex; flex-direction: column; gap: 10px; }
  .actions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; margin-top: 4px; }
  @media (max-width: 640px) {
    .sheet { top: auto; bottom: 0; translate: -50% 0; width: 100vw; border-radius: 18px 18px 0 0;
             padding-bottom: calc(22px + var(--safe-b)); }
    .actions { flex-direction: column-reverse; }
    .actions :global(.btn) { width: 100%; height: 46px; }
  }
</style>
