<script>
  import { duration } from '../lib/format.js'

  /** ms until voting locks; the ring drains over the final minute. */
  let { ms, size = 84 } = $props()

  const stroke = 7
  const r = $derived((size - stroke) / 2)
  const circumference = $derived(2 * Math.PI * r)
  const fraction = $derived(Math.min(1, ms / 60000))
  const urgent = $derived(ms <= 10000)
</script>

<div class="ring" class:urgent style:width="{size}px" style:height="{size}px">
  <svg width={size} height={size} viewBox="0 0 {size} {size}" aria-hidden="true">
    <defs>
      <linearGradient id="ring-grad" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="var(--accent)" />
        <stop offset="100%" stop-color="var(--accent-2)" />
      </linearGradient>
    </defs>
    <circle cx={size / 2} cy={size / 2} {r} fill="none" stroke="rgb(255 255 255 / 0.1)" stroke-width={stroke} />
    <circle
      cx={size / 2}
      cy={size / 2}
      {r}
      fill="none"
      stroke="url(#ring-grad)"
      stroke-width={stroke}
      stroke-linecap="round"
      stroke-dasharray={circumference}
      stroke-dashoffset={circumference * (1 - fraction)}
      transform="rotate(-90 {size / 2} {size / 2})"
    />
  </svg>
  <span class="label" style:font-size="{size / 4.2}px">{ms < 60000 ? Math.ceil(ms / 1000) : duration(ms)}</span>
</div>

<style>
  .ring {
    position: relative;
    display: grid;
    place-items: center;
    flex: none;
  }
  svg {
    position: absolute;
    inset: 0;
  }
  svg circle {
    transition: stroke-dashoffset 0.25s linear;
  }
  .label {
    font-weight: 800;
    font-variant-numeric: tabular-nums;
  }
  .urgent {
    animation: pulse 1s ease-in-out infinite;
  }
  .urgent .label {
    color: var(--accent);
  }
  @keyframes pulse {
    50% {
      transform: scale(1.06);
    }
  }
</style>
