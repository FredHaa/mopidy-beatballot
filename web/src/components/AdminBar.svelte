<script>
  import Source from './Source.svelte'
  import { admin, fetchLogins, party } from '../lib/party.svelte.js'

  const s = $derived(party.state)
  const paused = $derived(s?.paused_by_host || s?.playback === 'paused')
  let playlists = $state(null) // null until the host starts editing
  let tidal = $state(null)

  // Poll for a pending Tidal login so the host can approve it from here.
  $effect(() => {
    let alive = true
    const poll = async () => {
      try {
        const logins = await fetchLogins()
        if (alive) tidal = logins.tidal
      } catch {
        // Try again on the next tick.
      }
    }
    poll()
    const timer = setInterval(poll, 4000)
    return () => {
      alive = false
      clearInterval(timer)
    }
  })

  function savePlaylists(event) {
    event.preventDefault()
    admin('playlists', playlists ?? '')
    playlists = null
  }
</script>

<section class="admin">
  <h4>Host controls</h4>

  {#if tidal && tidal.state !== 'logged_in'}
    <div class="login">
      <strong>Connect Tidal</strong>
      {#if tidal.url}
        <p>Open the link and log in with the party's Tidal account. Code <code>{tidal.code}</code>, expires in {Math.ceil(tidal.expires_in / 60)} min.</p>
        <a class="btn" href={tidal.url} target="_blank" rel="noreferrer">Log in to Tidal ↗</a>
      {:else if tidal.state === 'error'}
        <p>Couldn't reach Tidal. Retrying…</p>
      {:else}
        <p>Checking the Tidal login…</p>
      {/if}
    </div>
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

  {#if s?.sources?.length}
    <div class="sources">
      {#each s.sources as src (src.id)}
        <span class:paused={src.paused}>
          <Source source={src.id} /> {src.tracks} songs{#if src.paused}&nbsp;· paused, keeps failing{/if}
        </span>
      {/each}
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
  .login {
    padding: 0.9rem;
    border-radius: 0.875rem;
    background: rgb(95 227 240 / 0.08);
    border: 1px solid rgb(95 227 240 / 0.35);
  }
  .login p {
    margin: 0.3rem 0 0.7rem;
    font-size: 0.88rem;
  }
  .login code {
    font-weight: 800;
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
