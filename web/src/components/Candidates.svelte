<script>
  import { flip } from 'svelte/animate'
  import { fly } from 'svelte/transition'
  import VoteCard from './VoteCard.svelte'
  import { admin, party, retract, vote } from '../lib/party.svelte.js'

  let { compact = false, interactive = true } = $props()

  const me = $derived(party.session?.user)
  // Most votes first; ties keep the server's order (oldest first).
  const sorted = $derived(
    (party.state?.round.candidates ?? [])
      .map((c, i) => ({ c, i }))
      .sort((a, b) => b.c.votes - a.c.votes || a.i - b.i)
      .map(({ c }) => c),
  )
  const maxVotes = $derived(Math.max(1, ...sorted.map((c) => c.votes)))
  const myVote = $derived(sorted.find((c) => c.voters.some((v) => v.id === me?.id))?.track.uri)

  function toggle(uri) {
    if (!interactive) return
    if (navigator.vibrate) navigator.vibrate(12)
    if (myVote === uri) retract()
    else vote(uri)
  }
</script>

<div class="list">
  {#each sorted as candidate (candidate.track.uri)}
    <div animate:flip={{ duration: 350 }} in:fly={{ y: 20, duration: 250 }}>
      <VoteCard
        {candidate}
        {compact}
        {maxVotes}
        mine={interactive && myVote === candidate.track.uri}
        onvote={() => toggle(candidate.track.uri)}
        onremove={interactive && me?.admin ? () => admin('remove', candidate.track.uri) : null}
      />
    </div>
  {:else}
    <p class="muted empty">
      {party.state?.suggestions_only
        ? 'Every song here is picked by you — search and add one!'
        : 'No songs in this round yet — add one!'}
    </p>
  {/each}
</div>

<style>
  .list {
    display: grid;
    gap: 0.8rem;
  }
  .empty {
    text-align: center;
    padding: 2rem 0;
  }
</style>
