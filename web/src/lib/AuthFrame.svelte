<script>
  let { children } = $props()
</script>

<div class="frame">
  <main class="panel rise">
    <header>
      <span class="eyebrow">Dayalbagh</span>
      <h1>Truck Tracking</h1>
      <p>Recording truck and trolley movements during the harvest. For members of the reporting team.</p>
    </header>
    <div class="body">{@render children()}</div>
  </main>
</div>

<style>
  .frame {
    min-height: 100dvh; display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 24px; padding: 32px 20px;
  }
  .panel {
    width: 100%; max-width: 400px; padding: 32px 28px 28px; border-radius: var(--r-lg);
    background: var(--surface); box-shadow: inset 0 0 0 1px var(--hair-2), var(--shadow);
    display: flex; flex-direction: column; gap: 24px;
  }
  header { display: flex; flex-direction: column; gap: 6px; padding-bottom: 20px; border-bottom: 1px solid var(--hair-2); }
  h1 { font-size: 24px; letter-spacing: -0.025em; }
  header p { font-size: 14px; color: var(--ink-2); line-height: 1.5; margin-top: 4px; }
  .body { display: flex; flex-direction: column; gap: 18px; }
  @media (max-width: 480px) {
    .frame { justify-content: flex-start; padding-top: 12vh; }
    .panel { padding: 26px 20px 22px; }
  }
</style>
