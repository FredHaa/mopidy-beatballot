<script>
  import Guest from './components/Guest.svelte'
  import Host from './components/Host.svelte'
  import HubAdmin from './components/HubAdmin.svelte'
  import Join from './components/Join.svelte'
  import Landing from './components/Landing.svelte'
  import Toast from './components/Toast.svelte'
  import WinnerOverlay from './components/WinnerOverlay.svelte'
  import { SLUG, connect, party } from './lib/party.svelte.js'

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

{#if !SLUG}
  {#if route === '#/hub'}<HubAdmin />{:else}<Landing />{/if}
{:else if !party.session}
  <Join />
{:else if route === '#/host'}
  <Host />
{:else}
  <Guest />
{/if}

{#if SLUG && party.session}<WinnerOverlay />{/if}
<Toast />
