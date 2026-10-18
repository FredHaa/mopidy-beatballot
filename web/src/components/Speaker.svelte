<script>
  import NowPlaying from './NowPlaying.svelte'
  import { party } from '../lib/party.svelte.js'
  import { setVolume, speaker, start, stop } from '../lib/speaker.svelte.js'

  const isHost = $derived(Boolean(party.session?.user?.admin))
  const onHub = $derived(party.state?.settings?.mode === 'hub')
  const room = $derived(party.room?.name ?? 'this party')

  // Leaving the page (back to voting) stops the speaker.
  $effect(() => () => speaker.active && stop())

  function confirmLeave(event) {
    if (speaker.active && !confirm('Stop playing on this device?')) event.preventDefault()
  }
</script>

<svelte:window onbeforeunload={(e) => speaker.active && (e.preventDefault(), (e.returnValue = ''))} />

<div class="page">
  <header>
    <span class="brand">🔊 <span class="gradient-text">Speaker</span></span>
    <a class="back muted" href="#/" onclick={confirmLeave}>← Back to voting</a>
  </header>

  {#if !isHost || !onHub}
    <section class="card">
      <h2>Only for the host</h2>
      <p class="muted">
        {onHub
          ? 'Join with the host PIN to play the party on this device.'
          : 'This party plays on its own speakers, not on remote players.'}
      </p>
    </section>
  {:else if !speaker.active}
    <section class="card intro">
      <h2>Play {room} on this device</h2>
      <p class="muted">
        The music comes out of this browser instead of the party's player. Keep this tab open, the screen on and the
        charger plugged in. It works best on a laptop, tablet or TV browser.
      </p>
      {#if party.state?.player?.online}
        <p class="warn">{party.state.player.name ?? 'Another player'} is playing now. Starting here takes over.</p>
      {/if}
      {#if speaker.error}<p class="error">{speaker.error}</p>{/if}
      <button class="btn big" onclick={start}>▶ Start playing here</button>
    </section>
  {:else}
    {#if party.state}<NowPlaying large />{/if}
    <section class="card controls">
      <div class="status">
        <span class="dot" class:on={speaker.connected}></span>
        {speaker.connected ? `Playing ${room} on this device` : 'Connecting to the party…'}
      </div>
      {#if speaker.error}<p class="error">{speaker.error}</p>{/if}
      <label class="volume">
        <span>Volume</span>
        <input type="range" min="0" max="1" step="0.01" value={speaker.volume} oninput={(e) => setVolume(Number(e.currentTarget.value))} />
      </label>
      <button class="btn ghost" onclick={() => stop()}>■ Stop playing here</button>
    </section>
  {/if}
</div>

<style>
  .page {
    max-width: 720px;
    margin: 0 auto;
    padding: calc(12px + env(safe-area-inset-top)) 16px 48px;
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 1rem;
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .brand {
    font-weight: 900;
    font-size: 1.25rem;
  }
  .back {
    font-size: 0.9rem;
  }
  .card {
    padding: 1.2rem;
    border-radius: var(--radius);
    background: var(--card);
    border: 1px solid var(--border);
    display: grid;
    gap: 0.8rem;
  }
  h2,
  p {
    margin: 0;
  }
  .intro {
    margin-top: 8vh;
    text-align: center;
    justify-items: center;
  }
  .big {
    padding: 1em 1.6em;
    font-size: 1.1rem;
  }
  .warn {
    color: var(--warn);
    font-weight: 600;
  }
  .error {
    color: var(--accent);
    font-weight: 600;
  }
  .status {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    font-weight: 700;
  }
  .dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--warn);
    box-shadow: 0 0 8px var(--warn);
  }
  .dot.on {
    background: var(--good);
    box-shadow: 0 0 8px var(--good);
  }
  .volume {
    display: grid;
    gap: 0.4rem;
    font-size: 0.85rem;
    font-weight: 600;
  }
  .volume input {
    accent-color: var(--accent);
    width: 100%;
  }
</style>
