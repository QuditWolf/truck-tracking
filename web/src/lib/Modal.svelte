<script>
  import { fade, fly } from 'svelte/transition'

  let { open = $bindable(false), title = '', children, actions } = $props()

  // Render at <body> level: an ancestor with a filter/transform (the blurred top bar, page transitions)
  // would otherwise become the containing block for position:fixed and push the sheet off-screen.
  function portal(node) {
    document.body.appendChild(node)
    return { destroy: () => node.remove() }
  }
</script>

<svelte:window onkeydown={(e) => open && e.key === 'Escape' && (open = false)} />

{#if open}
  <div class="portal" use:portal>
  <div class="scrim" transition:fade={{ duration: 150 }} onclick={() => (open = false)} role="presentation"></div>
  <div class="sheet" role="dialog" aria-modal="true" aria-label={title} transition:fly={{ y: 24, duration: 260, opacity: 0 }}>
    {#if title}<h3>{title}</h3>{/if}
    <div class="body">{@render children?.()}</div>
    {#if actions}<div class="actions">{@render actions()}</div>{/if}
  </div>
  </div>
{/if}

<style>
  .scrim { position: fixed; inset: 0; z-index: 40; background: rgba(22, 24, 27, .32); backdrop-filter: blur(2px); }
  .sheet {
    position: fixed; z-index: 41; left: 50%; top: 50%; translate: -50% -50%;
    width: min(440px, calc(100vw - 24px)); max-height: calc(100dvh - 32px); padding: 22px; border-radius: 18px;
    background: var(--surface); box-shadow: var(--shadow-lift);
    display: flex; flex-direction: column; gap: 14px;
  }
  h3 { font-size: 17px; }
  /* tall content scrolls inside the sheet; title and buttons stay put */
  .body { color: var(--ink-2); font-size: 14.5px; display: flex; flex-direction: column; gap: 10px;
          overflow-y: auto; min-height: 0; margin: 0 -22px; padding: 2px 22px; overscroll-behavior: contain; }
  h3, .actions { flex-shrink: 0; }
  .actions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; margin-top: 4px; }
  @media (max-width: 640px) {
    .sheet { top: auto; bottom: 0; translate: -50% 0; width: 100vw; border-radius: 18px 18px 0 0;
             max-height: calc(100dvh - 12px); padding-bottom: calc(22px + var(--safe-b)); }
    .actions { flex-direction: column-reverse; }
    .actions :global(.btn) { width: 100%; height: 46px; }
  }
</style>
