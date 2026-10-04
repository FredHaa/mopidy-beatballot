<script>
  import AdminBar from './AdminBar.svelte'
  import Art from './Art.svelte'
  import Candidates from './Candidates.svelte'
  import LockStatus from './LockStatus.svelte'
  import NowPlaying from './NowPlaying.svelte'
  import Search from './Search.svelte'
  import { leave, party } from '../lib/party.svelte.js'
  import { artists, initials, userColor } from '../lib/format.js'

  let searching = $state(false)
  const s = $derived(party.state)
  const me = $derived(party.session.user)
</script>

<div class="page">
  <header>
    <div class="brand">🗳️ <span class="gradient-text">Beat Ballot</span></div>
    {#if s?.test_mode}<span class="badge test">TEST MODE</span>{/if}
    <span class="conn" class:on={party.connected} title={party.connected ? 'Connected' : 'Reconnecting…'}></span>
    <button class="me" onclick={() => confirm('Leave the party on this device?') && leave()} title="Leave">
      <span class="avatar" style:background={userColor(me.id)}>{initials(me.name)}</span>
    </button>
  </header>

  {#if !s}
    <div class="loading muted">Connecting to the party…</div>
  {:else}
    <div class="area now"><NowPlaying /></div>
    <div class="area status panel"><LockStatus /></div>

    <section class="area ballot">
      <div class="section-head">
        <h2>Pick the next song</h2>
        <span class="muted">Round {s.round.id}</span>
      </div>
      <p class="muted tip">
        {#if s.suggestions_only}Guests add the songs.{/if}
        Tap a song to vote. Tap again to take it back.
        {#if s.settings.carry_over}Songs with {s.settings.carry_min_votes}+ votes that lose stay in the next round.{/if}
      </p>
      <Candidates />
    </section>

    {#if s.history.length}
      <section class="area history-area">
        <h2 class="section-head">Recently played</h2>
        <div class="history">
          {#each s.history as track, i (track.uri + i)}
            <div class="past">
              <Art {track} size={40} />
              <div class="truncate"><div class="truncate">{track.name}</div><div class="truncate muted small">{artists(track)}</div></div>
            </div>
          {/each}
        </div>
      </section>
    {/if}

    <div class="area extras">
      {#if me.admin}<AdminBar />{/if}
      <a class="host-link muted" href="#/host">Open big-screen view ↗</a>
    </div>
  {/if}
</div>

{#if s}
  <div class="fab-wrap">
    <button class="btn fab" onclick={() => (searching = true)}>＋ Add a song</button>
  </div>
{/if}

{#if searching}
  <Search onclose={() => (searching = false)} />
{/if}

<style>
  .page {
    /* minmax(0, …) stops long unbreakable text from widening the page */
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas: 'header' 'now' 'status' 'ballot' 'history' 'extras';
    max-width: 640px;
    margin: 0 auto;
    padding: calc(12px + env(safe-area-inset-top)) 16px 120px;
    display: grid;
    gap: 1rem;
  }
  header {
    grid-area: header;
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.2rem 0;
  }
  .brand {
    font-weight: 900;
    font-size: 1.25rem;
    letter-spacing: -0.02em;
    margin-right: auto;
  }
  .badge.test {
    background: rgb(255 204 61 / 0.15);
    color: var(--warn);
  }
  .conn {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--accent);
    box-shadow: 0 0 8px var(--accent);
  }
  .conn.on {
    background: var(--good);
    box-shadow: 0 0 8px var(--good);
  }
  .avatar {
    display: grid;
    place-items: center;
    width: 2.125rem;
    height: 2.125rem;
    border-radius: 50%;
    font-weight: 800;
    font-size: 0.8rem;
    color: #170f1f;
  }
  .area {
    min-width: 0;
  }
  /* Single-column grids: minmax(0, …) lets long titles truncate instead of
     pushing the column wider than the screen. */
  .now,
  .ballot,
  .history-area,
  .extras {
    grid-template-columns: minmax(0, 1fr);
  }
  .now {
    grid-area: now;
    display: grid;
    gap: 1rem;
  }
  .status {
    grid-area: status;
  }
  .ballot {
    grid-area: ballot;
    display: grid;
    gap: 1rem;
    align-content: start;
  }
  .history-area {
    grid-area: history;
    display: grid;
    gap: 1rem;
  }
  .extras {
    grid-area: extras;
    display: grid;
    gap: 1rem;
  }
  /* Wide landscape screens (tablets, laptops): ballot gets its own column. */
  @media (min-width: 1000px) and (orientation: landscape) {
    .page {
      max-width: 1240px;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr);
      grid-template-rows: auto auto auto auto 1fr;
      grid-template-areas:
        'header header'
        'now ballot'
        'status ballot'
        'history ballot'
        'extras ballot';
      column-gap: 2rem;
      align-items: start;
    }
    .ballot {
      position: sticky;
      top: 1rem;
    }
  }
  .loading {
    text-align: center;
    padding: 4rem 0;
  }
  .panel {
    padding: 1rem;
    border-radius: var(--radius);
    background: var(--card);
    border: 1px solid var(--border);
  }
  .section-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin: 0.8rem 0 0;
  }
  h2 {
    margin: 0;
    font-size: 1.15rem;
  }
  .tip {
    margin: -0.6rem 0 0.2rem;
    font-size: 0.82rem;
  }
  .history {
    display: flex;
    gap: 0.6rem;
    overflow-x: auto;
    padding-bottom: 0.4rem;
    scrollbar-width: none;
  }
  .past {
    flex: none;
    width: 180px;
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.5rem;
    border-radius: 14px;
    background: var(--card);
    font-size: 0.85rem;
  }
  .small {
    font-size: 0.75rem;
  }
  .host-link {
    justify-self: center;
    font-size: 0.85rem;
  }
  .fab-wrap {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    padding: 1rem 16px calc(1rem + env(safe-area-inset-bottom));
    display: flex;
    justify-content: center;
    background: linear-gradient(transparent, var(--bg) 45%);
    pointer-events: none;
  }
  .fab {
    pointer-events: auto;
    width: min(38rem, 100%);
    padding: 1em;
    font-size: 1.05rem;
  }
</style>
