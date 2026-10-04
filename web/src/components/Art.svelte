<script>
  let { track, size = 56 } = $props()
</script>

{#if track?.image}
  <img class="art" src={track.image} alt="" width={size} height={size} style:width="{size}px" style:height="{size}px" loading="lazy" />
{:else}
  <div class="art" style:width="{size}px" style:height="{size}px" style:font-size="{size / 2.4}px">♪</div>
{/if}
