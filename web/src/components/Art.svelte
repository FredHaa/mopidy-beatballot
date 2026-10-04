<script>
  // size: pixels at the default 16px root font size (scales with rem), or any CSS length.
  let { track, size = 56 } = $props()
  const css = $derived(typeof size === 'number' ? `${size / 16}rem` : size)
</script>

{#if track?.image}
  <img class="art" src={track.image} alt="" style:width={css} style:height={css} loading="lazy" />
{:else}
  <div class="art" style:width={css} style:height={css} style:font-size="calc({css} / 2.4)">♪</div>
{/if}
