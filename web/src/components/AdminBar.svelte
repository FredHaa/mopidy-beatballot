<script>
  import Services from './Services.svelte'
  import Source from './Source.svelte'
  import { admin, party } from '../lib/party.svelte.js'

  const s = $derived(party.state)
  const paused = $derived(s?.paused_by_host || s?.playback === 'paused')
  let playlists = $state(null) // null until the host starts editing

  // A standalone party's host connects the music services; on a hub that's
  // the hub owner's job (on the hub page).
  const onHub = $derived(s?.settings?.mode === 'hub')

  function setNumber(action, input, min, max) {
    const value = Math.round(Number(input.value))
    if (!Number.isFinite(value) || value < min || value > max) {
      input.value = String(s?.settings[action] ?? min)
      return
    }
    admin(action, value)
  }

  function savePlaylists(event) {
    event.preventDefault()
    admin('playlists', playlists ?? '')
    playlists = null
  }
</script>

<section class="admin">
  <h4>Host controls</h4>

  {#if s && !onHub}
    <Services token={party.session?.token} />
  {/if}

  {#if onHub}
    <a class="btn ghost speaker" href="#/speaker">
      🔊 {s?.player?.online && s.player.name?.endsWith("'s browser") ? 'Speaker page' : 'Play on this device'}
    </a>
  {/if}

  <div class="row">
    <button class="btn ghost" onclick={() => admin(paused ? 'resume' : 'pause')}>{paused ? '▶ Resume' : '⏸ Pause'}</button>
    <button class="btn ghost" onclick={() => admin('skip')}>⏭ Skip</button>
    <label class="toggle">
      <input type="checkbox" checked={s?.test_mode} onchange={(e) => admin('test_mode', e.currentTarget.checked)} />
      <span>Test mode</span>
    </label>
    <label class="toggle" title="Losing songs with {s?.settings.carry_min_votes ?? 2}+ votes stay in the next round, votes kept">
      <input type="checkbox" checked={s?.settings.carry_over} onchange={(e) => admin('carry_over', e.currentTarget.checked)} />
      <span>Carry over voted songs</span>
    </label>
  </div>

  <div class="numbers">
    <label>
      <span>Random picks per round</span>
      <input
        class="field"
        type="number"
        min="0"
        max="10"
        value={s?.settings.candidates ?? 3}
        onchange={(e) => setNumber('candidates', e.currentTarget, 0, 10)}
      />
    </label>
    <label>
      <span>Max songs on the ballot <small class="muted">(0 = no limit)</small></span>
      <input
        class="field"
        type="number"
        min="0"
        max="50"
        value={s?.settings.max_ballot ?? 0}
        onchange={(e) => setNumber('max_ballot', e.currentTarget, 0, 50)}
      />
    </label>
  </div>

  {#if s?.sources?.length}
    <div class="sources">
      {#each s.sources as src (src.id)}
        <span class:paused={src.paused}>
          <Source source={src.id} /> {src.tracks} songs{#if src.paused}&nbsp;· paused, keeps failing{/if}
        </span>
      {/each}
      {#if s.pool_discarded}
        <span class="muted" title="Songs that lost a round join the random picks">
          incl. {s.pool_discarded} from earlier ballots
        </span>
      {/if}
    </div>
  {/if}

  <form onsubmit={savePlaylists}>
    <label for="playlists">Playlists <span class="muted">(links from Spotify, Tidal or SoundCloud, one per line; leave empty for guest suggestions only)</span></label>
    <textarea
      id="playlists"
      class="field"
      rows="3"
      value={playlists ?? (s?.settings.playlists ?? []).join('\n')}
      oninput={(e) => (playlists = e.currentTarget.value)}
      placeholder="https://open.spotify.com/playlist/…&#10;https://tidal.com/browse/playlist/…"
    ></textarea>
    <ul class="status">
      {#each s?.playlists ?? [] as p (p.uri)}
        <li class="truncate">
          {#if p.login_pending}⏳{:else if p.tracks == null}⚠️{:else}✓{/if}
          <Source source={p.source} />
          <span class="muted">{p.login_pending ? 'waiting for login' : p.tracks == null ? 'could not load' : `${p.tracks} songs`}</span>
          <span class="uri muted">{p.uri}</span>
        </li>
      {/each}
    </ul>
    <button class="btn ghost" disabled={playlists === null}>Save playlists</button>
  </form>
</section>

<style>
  .admin {
    display: grid;
    gap: 0.9rem;
    padding: 1rem;
    border-radius: var(--radius);
    border: 1px dashed rgb(255 204 61 / 0.4);
    background: rgb(255 204 61 / 0.04);
  }
  h4 {
    margin: 0;
    color: var(--warn);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    align-items: center;
  }
  .btn {
    padding: 0.6em 1.1em;
    font-size: 0.9rem;
    text-decoration: none;
  }
  .toggle {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-weight: 600;
    font-size: 0.9rem;
  }
  .toggle input {
    accent-color: var(--accent);
    width: 1.1rem;
    height: 1.1rem;
  }
  .speaker {
    justify-self: start;
    text-decoration: none;
  }
  .numbers {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
    gap: 0.6rem;
    align-items: end; /* inputs line up when a label wraps */
  }
  .numbers label {
    display: grid;
    gap: 0.3rem;
    font-size: 0.82rem;
    font-weight: 600;
  }
  .numbers .field {
    max-width: 7rem;
    padding: 0.55em 0.8em;
  }
  .sources {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem 1rem;
    font-size: 0.82rem;
  }
  .sources .paused {
    color: var(--warn);
  }
  form {
    display: grid;
    gap: 0.5rem;
  }
  label {
    font-size: 0.85rem;
    font-weight: 600;
  }
  textarea {
    resize: vertical;
    font-size: 0.85rem;
  }
  .status {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 0.25rem;
    font-size: 0.78rem;
  }
  .uri {
    margin-left: 0.3rem;
    opacity: 0.7;
  }
  form .btn {
    justify-self: start;
  }
</style>
