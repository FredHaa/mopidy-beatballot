<script>
  import Art from './Art.svelte'
  import Source from './Source.svelte'
  import { party, positionMs } from '../lib/party.svelte.js'
  import { artists, duration } from '../lib/format.js'

  let { large = false } = $props()

  const now = $derived(party.state?.now)
  const pos = $derived(positionMs())
  const lockAt = $derived(now?.lock_at_ms)
</script>

<section class="now" class:large>
  {#if now?.track.image}
    <div class="backdrop" style:background-image="url({now.track.image})"></div>
  {/if}
  {#if now}
    <Art track={now.track} size={large ? 220 : 84} />
    <div class="meta">
      <div class="eyebrow">
        {#if party.state.paused_by_host || party.state.playback === 'paused'}⏸ Paused{:else}<span class="eq"><i></i><i></i><i></i></span> Now playing{/if}
      </div>
      <h2 class="truncate">{now.track.name}</h2>
      <p class="truncate muted">{artists(now.track)} <Source source={now.track.source} /></p>
      {#if now.end_ms}
        <div class="bar">
          <div class="fill" style:width="{(100 * pos) / now.end_ms}%"></div>
          {#if lockAt != null && !now.locked}
            <div class="lock" style:left="{(100 * lockAt) / now.end_ms}%" title="Voting locks here">🔒</div>
          {/if}
        </div>
        <div class="times muted"><span>{duration(pos)}</span><span>{duration(now.end_ms)}</span></div>
      {/if}
    </div>
  {:else}
    <div class="meta">
      <div class="eyebrow">Waiting for music</div>
      <h2>
        {party.state?.error ??
          (party.state?.suggestions_only
            ? 'Add a song to get the party started'
            : 'Vote or add a song to get the party started')}
      </h2>
    </div>
  {/if}
</section>

{#if party.state?.playback_error}
  <div class="playback-error" role="alert">⚠️ {party.state.playback_error}</div>
{/if}

<style>
  .playback-error {
    margin-top: -0.4rem;
    padding: 0.7rem 1rem;
    border-radius: 14px;
    background: rgb(255 204 61 / 0.1);
    border: 1px solid rgb(255 204 61 / 0.35);
    color: var(--warn);
    font-size: 0.88rem;
    font-weight: 600;
  }
  .now {
    position: relative;
    display: flex;
    gap: 1rem;
    align-items: center;
    padding: 1rem;
    border-radius: var(--radius);
    background: var(--card);
    border: 1px solid var(--border);
    overflow: hidden;
    isolation: isolate;
  }
  .backdrop {
    position: absolute;
    inset: -40px;
    z-index: -1;
    background-size: cover;
    background-position: center;
    filter: blur(40px) saturate(1.6) brightness(0.45);
    transition: background-image 0.6s;
  }
  .meta {
    min-width: 0;
    flex: 1;
  }
  .eyebrow {
    font-size: 0.72rem;
    font-weight: 800;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--accent);
    display: flex;
    align-items: center;
    gap: 0.5em;
  }
  h2 {
    margin: 0.25em 0 0.1em;
    font-size: 1.2rem;
    letter-spacing: -0.01em;
  }
  p {
    margin: 0;
    font-size: 0.92rem;
  }
  .bar {
    position: relative;
    height: 6px;
    margin-top: 0.9rem;
    border-radius: 99px;
    background: rgb(255 255 255 / 0.12);
  }
  .fill {
    height: 100%;
    border-radius: inherit;
    background: var(--gradient);
    transition: width 0.25s linear;
  }
  .lock {
    position: absolute;
    top: 50%;
    transform: translate(-50%, -50%);
    font-size: 0.7rem;
    filter: drop-shadow(0 0 4px #000);
  }
  .times {
    display: flex;
    justify-content: space-between;
    margin-top: 0.35rem;
    font-size: 0.75rem;
    font-variant-numeric: tabular-nums;
  }
  .eq {
    display: inline-flex;
    align-items: flex-end;
    gap: 2px;
    height: 10px;
  }
  .eq i {
    width: 3px;
    background: var(--accent);
    animation: eq 0.9s ease-in-out infinite;
  }
  .eq i:nth-child(2) {
    animation-delay: -0.3s;
  }
  .eq i:nth-child(3) {
    animation-delay: -0.6s;
  }
  @keyframes eq {
    0%,
    100% {
      height: 3px;
    }
    50% {
      height: 10px;
    }
  }

  .large {
    flex-direction: column;
    text-align: center;
    padding: 2rem;
    gap: 1.5rem;
  }
  .large .meta {
    width: 100%;
  }
  .large .eyebrow {
    justify-content: center;
    font-size: 0.9rem;
  }
  .large h2 {
    font-size: 2.2rem;
    white-space: normal;
  }
  .large p {
    font-size: 1.2rem;
  }
</style>
