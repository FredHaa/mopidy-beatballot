<script>
  import qrcode from 'qrcode-generator'
  import AdminBar from './AdminBar.svelte'
  import Candidates from './Candidates.svelte'
  import LockStatus from './LockStatus.svelte'
  import NowPlaying from './NowPlaying.svelte'
  import { fetchInfo, party } from '../lib/party.svelte.js'

  // The big screen sizes everything from the viewport (see app.css), so it
  // fills any TV, landscape or portrait. A-/A+ fine-tune it per screen.
  const SCALE_KEY = 'beatballot.hostScale'
  const MIN_SCALE = 0.6
  const MAX_SCALE = 1.8
  let scale = $state(loadScale())

  function loadScale() {
    try {
      const v = Number(localStorage.getItem(SCALE_KEY))
      return v >= MIN_SCALE && v <= MAX_SCALE ? v : 1
    } catch {
      return 1
    }
  }

  function setScale(v) {
    scale = Math.round(Math.min(MAX_SCALE, Math.max(MIN_SCALE, v)) * 10) / 10
    try {
      localStorage.setItem(SCALE_KEY, String(scale))
    } catch {
      // Not remembered in private mode; fine.
    }
  }

  $effect(() => {
    const root = document.documentElement
    root.classList.add('host-view')
    root.style.setProperty('--host-scale', String(scale))
    return () => {
      root.classList.remove('host-view')
      root.style.removeProperty('--host-scale')
    }
  })

  function onKey(event) {
    if (event.target.closest?.('input, textarea')) return
    if (event.key === '+' || event.key === '=') setScale(scale + 0.1)
    if (event.key === '-' || event.key === '_') setScale(scale - 0.1)
    if (event.key === '0') setScale(1)
  }

  let info = $state({})
  $effect(() => {
    fetchInfo().then((i) => (info = i))
  })

  const joinUrl = $derived(info.public_url || `${location.origin}${import.meta.env.BASE_URL}`)
  const pin = $derived(party.pin ?? party.session.pin)
  const qrSvg = $derived.by(() => {
    const qr = qrcode(0, 'M')
    qr.addData(joinUrl)
    qr.make()
    return qr.createSvgTag({ cellSize: 6, margin: 2, scalable: true })
  })
  const s = $derived(party.state)
</script>

<svelte:window onkeydown={onKey} />

<div class="host">
  <header class="brand">
    <span class="title">🗳️ <span class="gradient-text">Beat Ballot</span></span>
    {#if s?.test_mode}<span class="badge test">TEST MODE</span>{/if}
    <span class="tools">
      <button onclick={() => setScale(scale - 0.1)} title="Smaller (−)" aria-label="Smaller text">A−</button>
      <button onclick={() => setScale(1)} title="Reset size (0)" aria-label="Reset text size">{Math.round(scale * 100)}%</button>
      <button onclick={() => setScale(scale + 0.1)} title="Bigger (+)" aria-label="Bigger text">A+</button>
      <a href="#/" title="Back to voting">✕</a>
    </span>
  </header>

  <section class="now">
    {#if s}<NowPlaying large />{/if}
  </section>

  <section class="vote">
    {#if s}
      <LockStatus size={120} />
      <h2>Round {s.round.id}</h2>
      <div class="ballot">
        <Candidates compact interactive={false} />
      </div>
      {#if party.session.user.admin}
        <details class="controls">
          <summary>Host controls</summary>
          <AdminBar />
        </details>
      {/if}
    {:else}
      <p class="muted">Connecting…</p>
    {/if}
  </section>

  <aside class="join">
    <div class="qr">{@html qrSvg}</div>
    <div class="join-text">
      <div class="eyebrow">Join the vote</div>
      <div class="url">{joinUrl.replace(/^https?:\/\//, '')}</div>
      {#if pin}<div class="pin">PIN <strong>{pin}</strong></div>{/if}
    </div>
  </aside>
</div>

<style>
  /* Landscape: now playing + join on the left, the ballot on the right. */
  .host {
    --host-art: min(15rem, 30vh);
    height: 100dvh;
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1.3fr);
    grid-template-rows: auto minmax(0, 1fr) auto;
    grid-template-areas:
      'brand vote'
      'now vote'
      'join vote';
    gap: 1.5rem 2.5rem;
    padding: 2rem 2.5rem;
    overflow: hidden;
  }
  /* Portrait: one column, QR at the bottom. */
  @media (orientation: portrait) {
    .host {
      --host-art: min(10rem, 15vh);
      grid-template-columns: minmax(0, 1fr);
      grid-template-rows: auto auto minmax(0, 1fr) auto;
      grid-template-areas: 'brand' 'now' 'vote' 'join';
      padding: 2rem;
    }
    /* Art beside the title, so the ballot gets the height. */
    .now :global(.now.large) {
      flex-direction: row;
      text-align: left;
      padding: 1.5rem;
    }
    .now :global(.now.large .eyebrow) {
      justify-content: flex-start;
    }
    .now :global(.now.large h2) {
      font-size: 2rem;
    }
  }

  .brand {
    grid-area: brand;
    display: flex;
    align-items: center;
    gap: 0.8rem;
    min-width: 0;
  }
  .title {
    font-weight: 900;
    font-size: 2rem;
    letter-spacing: -0.03em;
    white-space: nowrap;
  }
  .badge.test {
    background: rgb(255 204 61 / 0.15);
    color: var(--warn);
    font-size: 0.8rem;
  }
  .tools {
    margin-left: auto;
    display: flex;
    gap: 0.3rem;
    opacity: 0.35;
    transition: opacity 0.2s;
  }
  .tools:hover,
  .tools:focus-within {
    opacity: 1;
  }
  .tools button,
  .tools a {
    min-width: 2.2rem;
    padding: 0.3rem 0.5rem;
    border-radius: 0.6rem;
    background: var(--card);
    border: 1px solid var(--border);
    color: var(--muted);
    font-size: 0.8rem;
    font-weight: 700;
    text-align: center;
    text-decoration: none;
  }

  .now {
    grid-area: now;
    min-height: 0;
    display: grid;
    align-content: start;
    gap: 1rem;
  }
  .now :global(.now) {
    max-height: 100%;
  }

  .vote {
    grid-area: vote;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 1.2rem;
  }
  h2 {
    margin: 0;
    font-size: 1.6rem;
  }
  /* The ballot takes the remaining height; extra songs fade out at the bottom. */
  .ballot {
    flex: 1 1 auto;
    min-height: 0;
    overflow: hidden;
    padding-top: 0.7rem; /* room for the "Your vote" tag */
    mask-image: linear-gradient(to bottom, #000 calc(100% - 3rem), transparent);
  }
  .controls {
    flex: none;
    max-height: 45%;
    overflow: auto;
  }
  .controls summary {
    cursor: pointer;
    color: var(--muted);
    font-size: 0.85rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 0.6rem;
  }

  .join {
    grid-area: join;
    display: flex;
    align-items: center;
    gap: 1.5rem;
    padding: 1.2rem;
    border-radius: var(--radius);
    background: var(--card);
    border: 1px solid var(--border);
    min-width: 0;
  }
  .qr {
    width: min(9.5rem, 18vh);
    flex: none;
    background: #fff;
    border-radius: 0.875rem;
    padding: 0.375rem;
  }
  .qr :global(svg) {
    display: block;
  }
  .join-text {
    min-width: 0;
  }
  .eyebrow {
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    color: var(--accent);
    font-size: 0.85rem;
  }
  .url {
    font-size: 1.3rem;
    font-weight: 700;
    margin: 0.3rem 0;
    overflow-wrap: anywhere;
  }
  .pin {
    font-size: 1.2rem;
    color: var(--muted);
  }
  .pin strong {
    color: var(--text);
    font-size: 2rem;
    letter-spacing: 0.2em;
    margin-left: 0.4rem;
  }
</style>
