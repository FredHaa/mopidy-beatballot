<script>
  import Guest from './components/Guest.svelte'
  import Host from './components/Host.svelte'
  import Join from './components/Join.svelte'
  import Toast from './components/Toast.svelte'
  import WinnerOverlay from './components/WinnerOverlay.svelte'
  import { connect, party } from './lib/party.svelte.js'

  let route = $state(location.hash)

  $effect(() => {
    const onHash = () => (route = location.hash)
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  })

  $effect(() => {
    if (party.session?.token) connect()
  })
</script>

{#if !party.session}
  <Join />
{:else if route === '#/host'}
  <Host />
{:else}
  <Guest />
{/if}

{#if party.session}<WinnerOverlay />{/if}
<Toast />
