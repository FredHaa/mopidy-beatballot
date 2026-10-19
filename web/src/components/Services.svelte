<script>
  // Connect Tidal and SoundCloud from the web app. Starting or stopping a
  // service restarts Beat Ballot (Mopidy loads music services at startup).
  import { getServices, serviceAction } from '../lib/services.js'
  import { toast } from '../lib/party.svelte.js'

  let { token } = $props()

  let services = $state(null)
  let restarting = $state(false) // Waiting for Beat Ballot to come back.
  let busy = $state(false)
  let scToken = $state('')

  const tidal = $derived(services?.tidal)
  const soundcloud = $derived(services?.soundcloud)
  // Poll fast while something is about to change.
  const waiting = $derived(restarting || tidal?.state === 'pending' || tidal?.state === 'checking')

  async function refresh() {
    try {
      const next = await getServices(token)
      if (restarting && !next.restarting) toast('Music services updated', 'ok')
      services = next
      restarting = next.restarting
    } catch (e) {
      // Down while restarting: keep waiting. Otherwise try again later.
      if (!restarting && e.status) services = null
    }
  }

  $effect(() => {
    if (!token) return
    refresh()
    const timer = setInterval(refresh, waiting ? 1500 : 5000)
    return () => clearInterval(timer)
  })

  async function act(service, action, body) {
    busy = true
    try {
      const next = await serviceAction(token, service, action, body)
      services = next
      restarting = next.restarting
      return true
    } catch (e) {
      toast(e.message)
      return false
    } finally {
      busy = false
    }
  }

  function disconnect(service, name) {
    if (confirm(`Disconnect ${name}? Its songs stop working, and Beat Ballot restarts (the music pauses a few seconds).`))
      act(service, 'disconnect')
  }

  async function connectSoundCloud(event) {
    event.preventDefault()
    if (await act('soundcloud', 'connect', { token: scToken.trim() })) scToken = ''
  }
</script>

{#if services && (tidal || soundcloud)}
  <section class="services">
    <h4>Music services</h4>

    {#if restarting}
      <p class="restarting">⏳ Restarting Beat Ballot to load the music services… back in a few seconds.</p>
    {:else if services.restart_needed || (!services.can_restart && ((tidal?.state === 'logged_in' && !tidal.enabled) || (soundcloud?.connected && !soundcloud.enabled)))}
      <p class="restarting">
        Restart Mopidy to apply this. (Outside Docker, also turn the service on in mopidy.conf: SoundCloud needs its token there as
        <code>auth_token</code>.)
      </p>
    {/if}

    {#if tidal}
      <div class="service">
        <div class="head">
          <strong>Tidal</strong>
          {#if tidal.state === 'logged_in'}
            <span class="ok">✓ {tidal.account ? `Connected as ${tidal.account}` : 'Connected'}</span>
          {:else}
            <span class="muted">Not connected</span>
          {/if}
        </div>

        {#if tidal.state === 'pending' && tidal.url}
          <p>
            Open the link and log in with the Tidal account to use. Code <code>{tidal.code}</code>,
            expires in {Math.ceil(tidal.expires_in / 60)} min.
          </p>
          <div class="actions">
            <a class="btn small" href={tidal.url} target="_blank" rel="noreferrer">Log in to Tidal ↗</a>
            <button class="btn ghost small" disabled={busy} onclick={() => act('tidal', 'disconnect')}>Cancel</button>
          </div>
        {:else if tidal.state === 'pending' || tidal.state === 'checking'}
          <p class="muted">Asking Tidal for a login link…</p>
        {:else if tidal.state === 'error'}
          <p class="muted">Couldn't reach Tidal. Retrying…</p>
          <div class="actions">
            <button class="btn ghost small" disabled={busy} onclick={() => act('tidal', 'disconnect')}>Cancel</button>
          </div>
        {:else if tidal.state === 'logged_in'}
          {#if !tidal.enabled && !restarting && services.can_restart}<p class="muted">Starting Tidal…</p>{/if}
          <div class="actions">
            <button class="btn ghost small danger" disabled={busy || restarting} onclick={() => disconnect('tidal', 'Tidal')}>Disconnect</button>
          </div>
        {:else}
          <p class="muted">Play Tidal playlists and let guests search Tidal. Needs a Tidal subscription.</p>
          <div class="actions">
            <button class="btn small" disabled={busy || restarting} onclick={() => act('tidal', 'connect')}>Connect Tidal</button>
          </div>
        {/if}
      </div>
    {/if}

    {#if soundcloud}
      <div class="service">
        <div class="head">
          <strong>SoundCloud</strong>
          {#if soundcloud.connected}
            <span class="ok">✓ {soundcloud.account ? `Connected as ${soundcloud.account}` : 'Connected'}</span>
          {:else}
            <span class="muted">Not connected</span>
          {/if}
        </div>

        {#if soundcloud.connected}
          {#if !soundcloud.enabled && !restarting && services.can_restart}<p class="muted">Starting SoundCloud…</p>{/if}
          {#if soundcloud.source === 'config'}
            <p class="muted">Set in the server settings (SOUNDCLOUD_AUTH_TOKEN).</p>
          {:else}
            <div class="actions">
              <button class="btn ghost small danger" disabled={busy || restarting} onclick={() => disconnect('soundcloud', 'SoundCloud')}>Disconnect</button>
            </div>
          {/if}
        {:else}
          <ol>
            <li>
              <a href={soundcloud.token_page} target="_blank" rel="noreferrer">Get a token on mopidy.com ↗</a>
              <span class="muted">(log in to SoundCloud there)</span>
            </li>
            <li>Paste it here:</li>
          </ol>
          <form onsubmit={connectSoundCloud}>
            <input class="field" bind:value={scToken} placeholder="SoundCloud token" autocomplete="off" spellcheck="false" />
            <button class="btn small" disabled={busy || restarting || !scToken.trim()}>{busy ? 'Checking…' : 'Connect'}</button>
          </form>
        {/if}
      </div>
    {/if}
  </section>
{/if}

<style>
  .services {
    display: grid;
    gap: 0.7rem;
    padding: 1rem;
    border-radius: var(--radius);
    background: rgb(95 227 240 / 0.06);
    border: 1px solid rgb(95 227 240 / 0.3);
    min-width: 0;
  }
  h4 {
    margin: 0;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: rgb(95 227 240);
  }
  .restarting {
    margin: 0;
    color: var(--warn);
    font-size: 0.88rem;
  }
  .service {
    display: grid;
    gap: 0.45rem;
    min-width: 0;
  }
  .service + .service {
    padding-top: 0.7rem;
    border-top: 1px solid var(--border);
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 0.3rem 1rem;
    font-size: 0.92rem;
  }
  .ok {
    color: var(--good);
    font-weight: 700;
    font-size: 0.85rem;
    overflow-wrap: anywhere;
  }
  .head .muted {
    font-size: 0.85rem;
  }
  p,
  ol {
    margin: 0;
    font-size: 0.86rem;
  }
  ol {
    padding-left: 1.2rem;
    display: grid;
    gap: 0.2rem;
  }
  ol a {
    color: var(--text);
    font-weight: 700;
  }
  code {
    font-weight: 800;
    letter-spacing: 0.1em;
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
  }
  form {
    display: flex;
    gap: 0.5rem;
    min-width: 0;
  }
  form .field {
    flex: 1;
    min-width: 0;
    padding: 0.55em 0.8em;
    font-size: 0.85rem;
  }
  .btn.small {
    padding: 0.45em 0.9em;
    font-size: 0.82rem;
    text-decoration: none;
    flex: none;
  }
  .danger {
    color: var(--accent);
  }
</style>
