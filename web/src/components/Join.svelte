<script>
  import { join } from '../lib/party.svelte.js'

  let name = $state('')
  let pin = $state(new URLSearchParams(location.search).get('pin') ?? '')
  let error = $state('')
  let busy = $state(false)

  async function submit(event) {
    event.preventDefault()
    busy = true
    error = ''
    try {
      await join(pin.trim(), name.trim())
    } catch (e) {
      error = e.message
    } finally {
      busy = false
    }
  }
</script>

<main>
  <div class="logo">🗳️</div>
  <h1><span class="gradient-text">Beat Ballot</span></h1>
  <p class="muted">Vote on what plays next.</p>

  <form onsubmit={submit}>
    <label>
      <span>Your name</span>
      <input class="field" bind:value={name} maxlength="24" autocomplete="nickname" placeholder="DJ Disco" required />
    </label>
    <label>
      <span>Party PIN</span>
      <input class="field pin" bind:value={pin} inputmode="numeric" autocomplete="off" placeholder="••••" required />
    </label>
    {#if error}<p class="error">{error}</p>{/if}
    <button class="btn" disabled={busy || !name.trim() || !pin.trim()}>
      {busy ? 'Joining…' : "Let's party"}
    </button>
  </form>
</main>

<style>
  main {
    min-height: 100dvh;
    display: grid;
    place-content: center;
    justify-items: center;
    text-align: center;
    padding: 24px 16px;
  }
  .logo {
    font-size: 4rem;
    animation: bob 2.4s ease-in-out infinite;
  }
  h1 {
    margin: 0.2em 0 0;
    font-size: clamp(2.4rem, 9vw, 3.4rem);
    letter-spacing: -0.03em;
  }
  p {
    margin: 0.4em 0 2em;
  }
  form {
    width: min(360px, 90vw);
    display: grid;
    gap: 1rem;
    text-align: left;
  }
  label span {
    display: block;
    margin: 0 0 0.4em 0.3em;
    font-size: 0.85rem;
    color: var(--muted);
    font-weight: 600;
  }
  .pin {
    letter-spacing: 0.4em;
    font-size: 1.3rem;
    text-align: center;
  }
  .btn {
    margin-top: 0.5rem;
    padding: 1em;
    font-size: 1.05rem;
  }
  .error {
    margin: 0;
    color: var(--accent);
    font-weight: 600;
    text-align: center;
  }
  @keyframes bob {
    50% {
      transform: translateY(-8px) rotate(-6deg);
    }
  }
</style>
