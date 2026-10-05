<script>
  import { fetchMode, roomUrl } from '../lib/party.svelte.js'

  let mode = $state(null)
  $effect(() => {
    fetchMode().then((m) => {
      // One party: go straight to it.
      if (m.rooms.length === 1 && location.hash !== '#/hub') location.replace(roomUrl(m.rooms[0].slug))
      else mode = m
    })
  })
</script>

<main>
  <div class="logo">🗳️</div>
  <h1><span class="gradient-text">Beat Ballot</span></h1>
  {#if mode}
    {#if mode.rooms.length}
      <p class="muted">Pick your party</p>
      <div class="rooms">
        {#each mode.rooms as room (room.id)}
          <a class="room" href={roomUrl(room.slug)}>{room.name} <span>→</span></a>
        {/each}
      </div>
    {:else}
      <p class="muted">No parties right now.</p>
    {/if}
    {#if mode.hub_admin}<a class="owner muted" href="#/hub">Host a party ↗</a>{/if}
  {/if}
</main>

<style>
  main {
    min-height: 100dvh;
    display: grid;
    place-content: center;
    justify-items: center;
    text-align: center;
    padding: 24px 16px;
    gap: 0.6rem;
  }
  .logo {
    font-size: 4rem;
  }
  h1 {
    margin: 0;
    font-size: clamp(2.4rem, 9vw, 3.4rem);
    letter-spacing: -0.03em;
  }
  .rooms {
    display: grid;
    gap: 0.7rem;
    width: min(360px, 90vw);
    margin-top: 0.8rem;
  }
  .room {
    display: flex;
    justify-content: space-between;
    padding: 1rem 1.2rem;
    border-radius: var(--radius);
    background: var(--card);
    border: 1px solid var(--border);
    color: var(--text);
    text-decoration: none;
    font-weight: 700;
  }
  .room span {
    color: var(--accent);
  }
  .owner {
    margin-top: 2rem;
    font-size: 0.85rem;
  }
</style>
