<script>
  import Guest from './components/Guest.svelte'
  import Host from './components/Host.svelte'
  import HubAdmin from './components/HubAdmin.svelte'
  import Join from './components/Join.svelte'
  import Landing from './components/Landing.svelte'
  import Speaker from './components/Speaker.svelte'
  import Toast from './components/Toast.svelte'
  import WinnerOverlay from './components/WinnerOverlay.svelte'
  import { AT_HOME, SLUG, connect, party } from './lib/party.svelte.js'

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

{#if AT_HOME && route === '#/hub'}
  <HubAdmin />
{:else if !SLUG}
  <Landing />
{:else if !party.session}
  <Join />
{:else if route === '#/host'}
  <Host />
{:else if route === '#/speaker'}
  <Speaker />
{:else}
  <Guest />
{/if}

{#if SLUG && party.session && !(AT_HOME && route === '#/hub')}<WinnerOverlay />{/if}
<Toast />
