<script>
  import Art from './Art.svelte'
  import Countdown from './Countdown.svelte'
  import { locksInMs, party } from '../lib/party.svelte.js'
  import { artists } from '../lib/format.js'

  let { size = 84 } = $props()

  const s = $derived(party.state)
  const ms = $derived(locksInMs())
  const locked = $derived(s?.now?.locked)
  const windowS = $derived(
    s?.test_mode ? s.settings.test_play_seconds - s.settings.test_lock_at : s?.settings.lock_before_end,
  )
</script>

<section class="status">
  {#if ms != null}
    <Countdown {ms} {size} />
  {/if}
  <div class="text">
    {#if s?.up_next}
      <div class="next">
        <Art track={s.up_next} size={34} />
        <div class="truncate"><span class="muted">Up next</span> <strong>{s.up_next.name}</strong> <span class="muted">· {artists(s.up_next)}</span></div>
      </div>
    {/if}
    {#if ms == null}
      <h3>Voting is open</h3>
      <p class="muted">The leading song plays as soon as the music stops.</p>
    {:else if locked}
      <h3>Voting for the song after</h3>
      <p class="muted">Locks {windowS}s before the next song ends.</p>
    {:else}
      <h3>{ms <= 10000 ? 'Last chance to vote!' : 'Voting closes in'}</h3>
      <p class="muted">The top song locks in {windowS}s before this one ends.</p>
    {/if}
  </div>
</section>

<style>
  .status {
    display: flex;
    align-items: center;
    gap: 1rem;
  }
  .text {
    min-width: 0;
    flex: 1;
  }
  h3 {
    margin: 0;
    font-size: 1.1rem;
  }
  p {
    margin: 0.2rem 0 0;
    font-size: 0.85rem;
  }
  .next {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    margin-bottom: 0.6rem;
    padding: 0.35rem 0.8rem 0.35rem 0.35rem;
    border-radius: 99px;
    background: rgb(61 220 151 / 0.12);
    border: 1px solid rgb(61 220 151 / 0.3);
    font-size: 0.85rem;
  }
  .next :global(.art) {
    border-radius: 50%;
  }
</style>
