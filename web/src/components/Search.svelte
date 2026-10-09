<script>
  import { fade, fly } from 'svelte/transition'
  import Art from './Art.svelte'
  import Source from './Source.svelte'
  import { party, search, suggest, toast } from '../lib/party.svelte.js'
  import { artists, duration } from '../lib/format.js'

  let { onclose } = $props()

  let query = $state('')
  let results = $state([])
  let loading = $state(false)
  let timer
  let latest = 0

  const candidateUris = $derived(new Set(party.state?.round.candidates.map((c) => c.track.uri) ?? []))
  const limit = $derived(party.state?.settings.max_suggestions_per_user ?? 1)

  function onInput() {
    clearTimeout(timer)
    const q = query.trim()
    if (q.length < 2) {
      results = []
      loading = false
      return
    }
    loading = true
    timer = setTimeout(async () => {
      const id = ++latest
      const found = await search(q)
      if (id === latest) {
        results = found
        loading = false
      }
    }, 300)
  }

  function add(track) {
    if (suggest(track.uri)) {
      toast(`Added “${track.name}” with your vote`, 'ok')
      onclose()
    }
  }

  function focus(node) {
    setTimeout(() => node.focus(), 50)
  }
</script>

<div class="scrim" transition:fade={{ duration: 150 }} onclick={onclose} role="presentation"></div>
<div class="sheet" transition:fly={{ y: 400, duration: 250 }} role="dialog" aria-label="Add a song">
  <div class="grab"></div>
  <div class="head">
    <h3>Add a song to the vote</h3>
    <button class="close" onclick={onclose} aria-label="Close">✕</button>
  </div>
  <p class="muted hint">You can add {limit} song{limit === 1 ? '' : 's'} per round.</p>
  <input class="field" type="search" placeholder="Search songs, artists…" bind:value={query} oninput={onInput} use:focus enterkeyhint="search" />
  <div class="results">
    {#if loading}
      {#each Array(4) as _}<div class="skeleton"></div>{/each}
    {:else if query.trim().length >= 2 && !results.length}
      <p class="muted empty">No songs found</p>
    {:else}
      {#each results as track (track.uri)}
        {@const added = candidateUris.has(track.uri)}
        <div class="row">
          <Art {track} size={48} />
          <div class="info">
            <div class="truncate title">{track.name}</div>
            <div class="truncate muted small"><Source source={track.source} /> {artists(track)} · {duration(track.length_ms)}</div>
          </div>
          <button class="btn add" disabled={added} onclick={() => add(track)}>{added ? 'In vote' : 'Add'}</button>
        </div>
      {/each}
    {/if}
  </div>
</div>

<style>
  .scrim {
    position: fixed;
    inset: 0;
    background: rgb(0 0 0 / 0.6);
    backdrop-filter: blur(4px);
    z-index: 50;
  }
  .sheet {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 51;
    max-width: 640px;
    margin: 0 auto;
    max-height: 88dvh;
    display: flex;
    flex-direction: column;
    padding: 0.6rem 1rem calc(1rem + env(safe-area-inset-bottom));
    background: var(--bg-2);
    border: 1px solid var(--border);
    border-bottom: 0;
    border-radius: 24px 24px 0 0;
    box-shadow: var(--shadow);
  }
  .grab {
    width: 40px;
    height: 4px;
    border-radius: 9px;
    background: rgb(255 255 255 / 0.2);
    margin: 0 auto 0.6rem;
  }
  .head {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  h3 {
    margin: 0;
  }
  .close {
    font-size: 1.1rem;
    padding: 0.4rem;
    color: var(--muted);
  }
  .hint {
    margin: 0.2rem 0 0.8rem;
    font-size: 0.85rem;
  }
  .results {
    overflow-y: auto;
    margin-top: 0.8rem;
    min-height: 200px;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 0.8rem;
    padding: 0.55rem 0.2rem;
    border-bottom: 1px solid rgb(255 255 255 / 0.05);
  }
  .info {
    flex: 1;
    min-width: 0;
  }
  .title {
    font-weight: 650;
  }
  .small {
    font-size: 0.82rem;
  }
  .add {
    padding: 0.5em 1em;
    font-size: 0.85rem;
  }
  .empty {
    text-align: center;
    margin-top: 2rem;
  }
  .skeleton {
    height: 56px;
    margin: 0.5rem 0;
    border-radius: 12px;
    background: linear-gradient(90deg, var(--card) 0%, var(--card-hover) 50%, var(--card) 100%);
    background-size: 200% 100%;
    animation: shimmer 1.2s infinite;
  }
  @keyframes shimmer {
    to {
      background-position: -200% 0;
    }
  }
</style>
