<script>
  import { fade, scale } from 'svelte/transition'
  import Art from './Art.svelte'
  import { party } from '../lib/party.svelte.js'
  import { artists } from '../lib/format.js'

  let shown = $state(null)
  let seenRound = null
  let timer

  $effect(() => {
    const w = party.state?.last_winner
    if (!w) return
    if (seenRound !== null && w.round !== seenRound) {
      shown = w
      clearTimeout(timer)
      timer = setTimeout(() => (shown = null), 3500)
    }
    seenRound = w.round
  })
</script>

{#if shown}
  <div class="overlay" transition:fade={{ duration: 200 }} onclick={() => (shown = null)} role="presentation">
    <div class="box" in:scale={{ start: 0.7, duration: 400 }}>
      <div class="lock">🔒</div>
      <div class="eyebrow">Locked in</div>
      <Art track={shown.track} size={160} />
      <h2>{shown.track.name}</h2>
      <p class="muted">{artists(shown.track)}</p>
      <p class="votes">{shown.votes ? `${shown.votes} vote${shown.votes === 1 ? '' : 's'}` : 'Random pick — nobody voted!'}</p>
    </div>
  </div>
{/if}

<style>
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 90;
    display: grid;
    place-items: center;
    background: rgb(13 10 20 / 0.85);
    backdrop-filter: blur(8px);
  }
  .box {
    display: grid;
    justify-items: center;
    text-align: center;
    padding: 2rem;
  }
  .lock {
    font-size: 2.5rem;
    animation: drop 0.5s cubic-bezier(0.3, 1.6, 0.5, 1);
  }
  .eyebrow {
    margin: 0.3rem 0 1rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.2em;
    color: var(--accent);
  }
  .box :global(.art) {
    box-shadow: 0 20px 60px rgb(255 61 154 / 0.4);
  }
  h2 {
    margin: 1rem 0 0.2rem;
    font-size: 1.6rem;
  }
  p {
    margin: 0;
  }
  .votes {
    margin-top: 0.8rem;
    font-weight: 700;
  }
  @keyframes drop {
    from {
      transform: translateY(-40px) scale(1.4);
      opacity: 0;
    }
  }
</style>
