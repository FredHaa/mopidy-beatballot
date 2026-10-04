<script>
  import qrcode from 'qrcode-generator'
  import AdminBar from './AdminBar.svelte'
  import Candidates from './Candidates.svelte'
  import LockStatus from './LockStatus.svelte'
  import NowPlaying from './NowPlaying.svelte'
  import { fetchInfo, party } from '../lib/party.svelte.js'

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

<div class="host">
  <div class="left">
    <div class="brand">🗳️ <span class="gradient-text">Beat Ballot</span>{#if s?.test_mode}<span class="badge test">TEST MODE</span>{/if}</div>
    {#if s}<NowPlaying large />{/if}
    <div class="join">
      <div class="qr">{@html qrSvg}</div>
      <div>
        <div class="eyebrow">Join the vote</div>
        <div class="url">{joinUrl.replace(/^https?:\/\//, '')}</div>
        {#if pin}<div class="pin">PIN <strong>{pin}</strong></div>{/if}
      </div>
    </div>
  </div>
  <div class="right">
    {#if s}
      <LockStatus size={120} />
      <h2>Round {s.round.id}</h2>
      <Candidates compact interactive={false} />
      {#if party.session.user.admin}<AdminBar />{/if}
    {:else}
      <p class="muted">Connecting…</p>
    {/if}
    <a class="muted back" href="#/">← Back to voting</a>
  </div>
</div>

<style>
  .host {
    min-height: 100dvh;
    display: grid;
    grid-template-columns: minmax(320px, 1fr) minmax(360px, 1.2fr);
    gap: 2.5rem;
    padding: 2.5rem;
    max-width: 1600px;
    margin: 0 auto;
  }
  .left {
    position: sticky;
    top: 2.5rem;
    height: calc(100dvh - 5rem);
  }
  .left,
  .right {
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
    min-width: 0;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 0.8rem;
    font-weight: 900;
    font-size: 2rem;
    letter-spacing: -0.03em;
  }
  .badge.test {
    background: rgb(255 204 61 / 0.15);
    color: var(--warn);
    font-size: 0.8rem;
  }
  .join {
    display: flex;
    align-items: center;
    gap: 1.5rem;
    padding: 1.2rem;
    border-radius: var(--radius);
    background: var(--card);
    border: 1px solid var(--border);
    margin-top: auto;
  }
  .qr {
    width: 150px;
    flex: none;
    background: #fff;
    border-radius: 14px;
    padding: 6px;
  }
  .qr :global(svg) {
    display: block;
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
    word-break: break-all;
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
  h2 {
    margin: 0;
    font-size: 1.6rem;
  }
  .back {
    margin-top: auto;
    font-size: 0.85rem;
  }
  @media (max-width: 900px) {
    .left {
      position: static;
      height: auto;
    }
    .host {
      grid-template-columns: 1fr;
      padding: 16px;
    }
  }
</style>
