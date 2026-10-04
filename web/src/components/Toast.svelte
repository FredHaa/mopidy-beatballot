<script>
  import { fly } from 'svelte/transition'
  import { party } from '../lib/party.svelte.js'
</script>

{#if party.toast}
  {#key party.toast.id}
    <div class="toast {party.toast.kind}" role="status" transition:fly={{ y: 30, duration: 200 }}>
      {party.toast.message}
    </div>
  {/key}
{/if}

<style>
  .toast {
    position: fixed;
    left: 50%;
    bottom: calc(24px + env(safe-area-inset-bottom));
    transform: translateX(-50%);
    z-index: 100;
    max-width: min(92vw, 420px);
    padding: 0.8em 1.2em;
    border-radius: 14px;
    background: #2a1830;
    border: 1px solid rgb(255 61 154 / 0.5);
    box-shadow: var(--shadow);
    font-weight: 600;
    text-align: center;
  }
  .toast.ok {
    background: #11291f;
    border-color: rgb(61 220 151 / 0.5);
  }
</style>
