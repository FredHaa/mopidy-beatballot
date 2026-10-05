<script>
  import Art from './Art.svelte'
  import {
    createRoom,
    deleteRoom,
    listRooms,
    login,
    logout,
    owner,
    pairPlayer,
    tidalLogin,
    unpairPlayer,
    updateRoom,
  } from '../lib/hub.svelte.js'
  import { roomUrl, toast } from '../lib/party.svelte.js'
  import { artists } from '../lib/format.js'

  let pin = $state('')
  let error = $state('')
  let rooms = $state([])
  let tidal = $state(null)
  let pairing = $state({}) // room id -> { code, expiresAt }
  let editing = $state(null) // room id
  let draft = $state({})
  let newRoom = $state({ name: '', pin: '', admin_pin: '' })
  let busy = $state(false)

  async function refresh() {
    try {
      rooms = await listRooms()
      tidal = await tidalLogin()
    } catch (e) {
      if (owner.token) toast(e.message)
    }
  }

  $effect(() => {
    if (!owner.token) return
    refresh()
    const timer = setInterval(refresh, 3000)
    return () => clearInterval(timer)
  })

  async function submitLogin(event) {
    event.preventDefault()
    error = ''
    try {
      await login(pin.trim())
      pin = ''
    } catch (e) {
      error = e.message
    }
  }

  async function run(fn, done) {
    busy = true
    try {
      await fn()
      if (done) toast(done, 'ok')
      await refresh()
    } catch (e) {
      toast(e.message)
    } finally {
      busy = false
    }
  }

  function create(event) {
    event.preventDefault()
    const fields = Object.fromEntries(Object.entries(newRoom).filter(([, v]) => v.trim()))
    run(async () => {
      await createRoom(fields)
      newRoom = { name: '', pin: '', admin_pin: '' }
    }, 'Party created')
  }

  function startEdit(room) {
    editing = room.id
    draft = { name: room.name, slug: room.slug, pin: room.pin, admin_pin: room.admin_pin, listed: room.listed }
  }

  function saveEdit(event, room) {
    event.preventDefault()
    run(async () => {
      await updateRoom(room.id, draft)
      editing = null
    }, 'Saved')
  }

  function pair(room) {
    run(async () => {
      const { code, expires_in } = await pairPlayer(room.id)
      pairing = { ...pairing, [room.id]: { code, expiresAt: Date.now() + expires_in * 1000 } }
    })
  }

  function unpair(room) {
    if (confirm(`Disconnect the player from “${room.name}”? It will need a new pairing code.`))
      run(() => unpairPlayer(room.id), 'Player unpaired')
  }

  function remove(room) {
    if (confirm(`Delete “${room.name}”? Guests and its player are disconnected.`))
      run(() => deleteRoom(room.id), 'Party deleted')
  }

  function joinUrl(room) {
    return room.join_url ?? roomUrl(room.slug)
  }

  function command(code) {
    return [
      'docker run -d --name beatballot-player --restart unless-stopped \\',
      '  --device /dev/snd --group-add audio -v beatballot-player:/var/lib/mopidy \\',
      `  -e BALLOT_MODE=player -e BALLOT_HUB_URL=${location.origin} \\`,
      `  -e BALLOT_PAIR_CODE=${code} -e AUDIO_OUTPUT=alsasink \\`,
      '  ghcr.io/fredhaa/beatballot:latest',
    ].join('\n')
  }

  async function copy(text, what) {
    try {
      await navigator.clipboard.writeText(text)
      toast(`${what} copied`, 'ok')
    } catch {
      toast(`Couldn't copy; select it instead`)
    }
  }
</script>

<div class="page">
  <header>
    <a class="brand" href="./">🗳️ <span class="gradient-text">Beat Ballot</span> <span class="muted">hub</span></a>
    {#if owner.token}<button class="btn ghost small" onclick={logout}>Log out</button>{/if}
  </header>

  {#if !owner.token}
    <form class="card login" onsubmit={submitLogin}>
      <h2>Hub owner</h2>
      <p class="muted">Create parties, pair players and connect Tidal.</p>
      <input class="field pin" type="password" bind:value={pin} placeholder="Hub PIN" autocomplete="current-password" required />
      {#if error}<p class="error">{error}</p>{/if}
      <button class="btn" disabled={!pin.trim()}>Log in</button>
    </form>
  {:else}
    {#if tidal && tidal.state !== 'logged_in'}
      <section class="card tidal">
        <strong>Connect Tidal</strong>
        {#if tidal.url}
          <p>Log in with the hub's Tidal account. Code <code>{tidal.code}</code>, expires in {Math.ceil(tidal.expires_in / 60)} min.</p>
          <a class="btn" href={tidal.url} target="_blank" rel="noreferrer">Log in to Tidal ↗</a>
        {:else}
          <p class="muted">Checking the Tidal login…</p>
        {/if}
      </section>
    {/if}

    <section class="rooms">
      {#each rooms as room (room.id)}
        <article class="card room">
          <div class="head">
            <div>
              <h3>{room.name}</h3>
              <a class="link" href={joinUrl(room)} target="_blank" rel="noreferrer">{joinUrl(room).replace(/^https?:\/\//, '')}</a>
            </div>
            <span class="status" class:on={room.player.online}>
              {#if room.player.online}● {room.player.name ?? room.player_name ?? 'Player'} online{:else if room.paired}○ {room.player_name ?? 'Player'} offline{:else}○ No player{/if}
            </span>
          </div>

          {#if room.now_playing}
            <div class="now">
              <Art track={room.now_playing} size={40} />
              <div class="truncate"><strong>{room.now_playing.name}</strong> <span class="muted">· {artists(room.now_playing)}</span></div>
            </div>
          {/if}
          {#if room.error}<p class="warn">{room.error}</p>{/if}

          <div class="pins">
            <span>Guest PIN <strong>{room.pin}</strong></span>
            <span>Host PIN <strong>{room.admin_pin}</strong></span>
            {#if !room.listed}<span class="muted">Hidden from landing page</span>{/if}
          </div>

          {#if pairing[room.id] && !room.player.online}
            <div class="pairing">
              <p>Pairing code <strong class="code">{pairing[room.id].code}</strong> <span class="muted">(valid 15 min, used once)</span></p>
              <p class="muted small">Run on the player (Raspberry Pi or PC with speakers):</p>
              <pre>{command(pairing[room.id].code)}</pre>
              <button class="btn ghost small" onclick={() => copy(command(pairing[room.id].code), 'Command')}>Copy command</button>
            </div>
          {/if}

          {#if editing === room.id}
            <form class="edit" onsubmit={(e) => saveEdit(e, room)}>
              <label>Name <input class="field" bind:value={draft.name} required /></label>
              <label>Link <input class="field" bind:value={draft.slug} pattern="[a-z0-9-]+" required /></label>
              <label>Guest PIN <input class="field" bind:value={draft.pin} required /></label>
              <label>Host PIN <input class="field" bind:value={draft.admin_pin} required /></label>
              <label class="check"><input type="checkbox" bind:checked={draft.listed} /> Show on the landing page</label>
              <p class="muted small">Changing a PIN signs everyone out of this party.</p>
              <div class="actions">
                <button class="btn small" disabled={busy}>Save</button>
                <button type="button" class="btn ghost small" onclick={() => (editing = null)}>Cancel</button>
              </div>
            </form>
          {:else}
            <div class="actions">
              <a class="btn ghost small" href={joinUrl(room)} target="_blank" rel="noreferrer">Open</a>
              <a class="btn ghost small" href={`${joinUrl(room)}#/host`} target="_blank" rel="noreferrer">Big screen</a>
              <button class="btn ghost small" onclick={() => copy(joinUrl(room), 'Link')}>Copy link</button>
              <button class="btn ghost small" disabled={busy} onclick={() => pair(room)}>{room.paired ? 'Pair new player' : 'Pair player'}</button>
              {#if room.paired}<button class="btn ghost small" disabled={busy} onclick={() => unpair(room)}>Unpair</button>{/if}
              <button class="btn ghost small" onclick={() => startEdit(room)}>Edit</button>
              <button class="btn ghost small danger" disabled={busy} onclick={() => remove(room)}>Delete</button>
            </div>
          {/if}
        </article>
      {:else}
        <p class="muted">No parties yet: create one below.</p>
      {/each}
    </section>

    <form class="card create" onsubmit={create}>
      <h3>New party</h3>
      <input class="field" bind:value={newRoom.name} placeholder="Name, e.g. Klubhuset Friday" maxlength="60" required />
      <div class="two">
        <input class="field" bind:value={newRoom.pin} placeholder="Guest PIN (random if empty)" />
        <input class="field" bind:value={newRoom.admin_pin} placeholder="Host PIN (random if empty)" />
      </div>
      <button class="btn" disabled={busy || !newRoom.name.trim()}>Create party</button>
    </form>
  {/if}
</div>

<style>
  .page {
    max-width: 820px;
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
    color: var(--text);
    text-decoration: none;
  }
  .card {
    padding: 1.1rem;
    border-radius: var(--radius);
    background: var(--card);
    border: 1px solid var(--border);
    display: grid;
    gap: 0.7rem;
    min-width: 0;
  }
  .login {
    max-width: 380px;
    justify-self: center;
    width: 100%;
    margin-top: 10vh;
  }
  h2,
  h3 {
    margin: 0;
  }
  .pin {
    letter-spacing: 0.3em;
    text-align: center;
  }
  .error {
    margin: 0;
    color: var(--accent);
  }
  .tidal {
    background: rgb(95 227 240 / 0.08);
    border-color: rgb(95 227 240 / 0.35);
  }
  .tidal p {
    margin: 0;
  }
  .rooms {
    display: grid;
    gap: 1rem;
  }
  .head {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    align-items: start;
  }
  .head > div {
    min-width: 0;
  }
  .link {
    color: var(--muted);
    font-size: 0.85rem;
    overflow-wrap: anywhere;
  }
  .status {
    flex: none;
    font-size: 0.82rem;
    font-weight: 700;
    color: var(--muted);
  }
  .status.on {
    color: var(--good);
  }
  .now {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    font-size: 0.9rem;
  }
  .now > div {
    min-width: 0;
  }
  .warn {
    margin: 0;
    color: var(--warn);
    font-size: 0.85rem;
  }
  .pins {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem 1.2rem;
    font-size: 0.88rem;
    color: var(--muted);
  }
  .pins strong {
    color: var(--text);
    letter-spacing: 0.1em;
  }
  .pairing {
    padding: 0.8rem;
    border-radius: 0.8rem;
    background: rgb(255 204 61 / 0.06);
    border: 1px dashed rgb(255 204 61 / 0.4);
    min-width: 0;
  }
  .pairing p {
    margin: 0 0 0.4rem;
  }
  .code {
    font-size: 1.3rem;
    letter-spacing: 0.15em;
    color: var(--warn);
  }
  pre {
    margin: 0 0 0.6rem;
    padding: 0.7rem;
    border-radius: 0.6rem;
    background: rgb(0 0 0 / 0.35);
    font-size: 0.75rem;
    overflow-x: auto;
    white-space: pre;
  }
  .small {
    font-size: 0.8rem;
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
  }
  .btn.small {
    padding: 0.45em 0.9em;
    font-size: 0.82rem;
    text-decoration: none;
  }
  .danger {
    color: var(--accent);
  }
  .edit {
    display: grid;
    gap: 0.6rem;
  }
  .edit label {
    display: grid;
    gap: 0.3rem;
    font-size: 0.82rem;
    color: var(--muted);
  }
  .edit .check {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  .two {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
    gap: 0.6rem;
  }
</style>
