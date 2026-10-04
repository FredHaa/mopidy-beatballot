<script>
  // Small label saying which service a track streams from.
  const NAMES = { spotify: 'Spotify', tidal: 'Tidal', soundcloud: 'SoundCloud', file: 'Local', local: 'Local' }
  let { source } = $props()
</script>

{#if source}
  <span class="source {source}">{NAMES[source] ?? source}</span>
{/if}

<style>
  .source {
    display: inline-flex;
    align-items: center;
    gap: 0.35em;
    padding: 0.15em 0.55em;
    border-radius: 62.44rem;
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.02em;
    background: rgb(255 255 255 / 0.07);
    color: var(--muted);
    white-space: nowrap;
  }
  .source::before {
    content: '';
    width: 0.5em;
    height: 0.5em;
    border-radius: 50%;
    background: currentColor;
  }
  .spotify {
    color: #4cd982;
  }
  .tidal {
    color: #5fe3f0;
  }
  .soundcloud {
    color: #ff8a4c;
  }
</style>
