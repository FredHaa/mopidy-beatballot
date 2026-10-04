<script>
  import Art from './Art.svelte'
  import Source from './Source.svelte'
  import { artists, duration, initials, userColor } from '../lib/format.js'

  let { candidate, mine = false, maxVotes = 1, onvote, onremove = null, compact = false } = $props()

  const track = $derived(candidate.track)
</script>

<div class="card" class:mine class:leading={candidate.leading} class:compact>
  <button class="main" onclick={onvote} aria-pressed={mine} aria-label="Vote for {track.name}">
    <Art {track} size={compact ? 64 : 56} />
    <div class="info">
      <div class="title truncate">{track.name}</div>
      <div class="artist truncate muted">{artists(track)} · {duration(track.length_ms)}</div>
      <div class="tags">
        <Source source={track.source} />
        {#if candidate.leading}<span class="badge lead">🔥 Leading</span>{/if}
        {#if candidate.carried}<span class="badge carried">↻ Carried over</span>{/if}
        {#if candidate.origin === 'suggested'}<span class="badge">✨ {candidate.added_by ?? 'Guest'}</span>{/if}
      </div>
    </div>
    <div class="count" class:zero={!candidate.votes}>
      <strong>{candidate.votes}</strong>
      <small>{candidate.votes === 1 ? 'vote' : 'votes'}</small>
    </div>
  </button>
  <div class="footer">
    <div class="meter"><div style:width="{maxVotes ? (100 * candidate.votes) / maxVotes : 0}%"></div></div>
    <div class="voters">
      {#each candidate.voters.slice(0, 8) as v (v.id)}
        <span class="dot" style:background={userColor(v.id)} title={v.name}>{initials(v.name)}</span>
      {/each}
      {#if candidate.voters.length > 8}<span class="more muted">+{candidate.voters.length - 8}</span>{/if}
    </div>
    {#if onremove}
      <button class="remove" onclick={onremove} title="Remove from vote">✕</button>
    {/if}
  </div>
  {#if mine}<div class="check">✓ Your vote</div>{/if}
</div>

<style>
  .card {
    position: relative;
    border-radius: var(--radius);
    background: var(--card);
    border: 1.5px solid var(--border);
    transition:
      border-color 0.2s,
      background 0.2s,
      transform 0.15s;
  }
  .card:has(.main:active) {
    transform: scale(0.985);
  }
  .card.mine {
    border-color: var(--accent);
    background: linear-gradient(120deg, rgb(255 61 154 / 0.16), rgb(255 138 61 / 0.08));
  }
  .main {
    display: flex;
    align-items: center;
    gap: 0.85rem;
    width: 100%;
    padding: 0.85rem 0.9rem 0.5rem;
    text-align: left;
  }
  .info {
    min-width: 0;
    flex: 1;
  }
  .title {
    font-weight: 700;
  }
  .artist {
    font-size: 0.85rem;
    margin-top: 0.1em;
  }
  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.3rem;
    margin-top: 0.4rem;
  }
  .tags:empty {
    display: none;
  }
  .badge.lead {
    background: rgb(255 138 61 / 0.18);
    color: var(--accent-2);
  }
  .badge.carried {
    background: rgb(124 92 255 / 0.22);
    color: #b9a8ff;
  }
  .count {
    display: grid;
    justify-items: center;
    min-width: 3rem;
  }
  .count strong {
    font-size: 1.6rem;
    line-height: 1;
    font-variant-numeric: tabular-nums;
  }
  .count small {
    font-size: 0.68rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }
  .count.zero {
    opacity: 0.45;
  }
  .footer {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0 0.9rem 0.8rem;
  }
  .meter {
    flex: 1;
    height: 0.3125rem;
    border-radius: 6.188rem;
    background: rgb(255 255 255 / 0.08);
    overflow: hidden;
  }
  .meter div {
    height: 100%;
    background: var(--gradient);
    border-radius: inherit;
    transition: width 0.4s cubic-bezier(0.2, 0.9, 0.3, 1.2);
  }
  .voters {
    display: flex;
  }
  .dot {
    width: 1.375rem;
    height: 1.375rem;
    margin-left: -0.375rem;
    border-radius: 50%;
    border: 2px solid var(--bg);
    display: grid;
    place-items: center;
    font-size: 0.55rem;
    font-weight: 800;
    color: #170f1f;
  }
  .dot:first-child {
    margin-left: 0;
  }
  .more {
    font-size: 0.75rem;
    margin-left: 0.3rem;
  }
  .remove {
    padding: 0.2rem 0.4rem;
    color: var(--muted);
    border-radius: 0.5rem;
  }
  .remove:hover {
    color: var(--accent);
    background: var(--card-hover);
  }
  .check {
    position: absolute;
    top: -0.625rem;
    right: 0.875rem;
    padding: 0.15em 0.6em;
    border-radius: 6.188rem;
    background: var(--gradient);
    font-size: 0.7rem;
    font-weight: 800;
  }
  .compact .main {
    padding: 1rem 1.2rem 0.6rem;
  }
  .compact .title {
    font-size: 1.25rem;
  }
</style>
