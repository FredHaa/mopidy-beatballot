// This browser tab as the party's speaker: plays what the hub sends.
//
// Speaks the same protocol as the Docker/.deb player (agent.py): the hub
// sends commands with song ids and short-lived stream URLs, and gets status
// reports back. Mirrors Mopidy's play-once queue: the queue includes the
// current song, which leaves it when it ends; a song that fails to load
// stops playback but stays queued, so the hub notices and skips it.

import { party } from './party.svelte.js'

const BASE = import.meta.env.BASE_URL
const REPORT_EVERY_MS = 1000

export const speaker = $state({
  active: false,
  connected: false,
  state: 'stopped', // stopped | playing | paused
  current: null, // { id, title, artist }
  error: null,
  volume: 1,
})

let ws = null
let retries = 0
let reconnectTimer = null
let reportTimer = null
let wakeLock = null
let ack = 0
let queue = [] // [{ id, url, title, artist, length_ms }]
let currentId = null
const audios = [new Audio(), new Audio()]
let active = 0 // index of the element playing the current song

for (const audio of audios) {
  audio.preload = 'auto'
  audio.addEventListener('ended', () => audio === audios[active] && advance())
  audio.addEventListener('error', () => audio === audios[active] && failed())
  audio.addEventListener('pause', report)
  audio.addEventListener('playing', report)
}

function current() {
  return queue.find((s) => s.id === currentId) ?? null
}

function setState(state) {
  speaker.state = state
  const song = current()
  speaker.current = song ? { id: song.id, title: song.title, artist: song.artist } : null
  if ('mediaSession' in navigator) {
    navigator.mediaSession.playbackState = state === 'playing' ? 'playing' : 'paused'
    navigator.mediaSession.metadata = song
      ? new MediaMetadata({ title: song.title ?? '', artist: song.artist ?? '', album: party.room?.name ?? '' })
      : null
  }
  report()
}

function play(song) {
  // Use the element that preloaded this song, if any.
  const other = 1 - active
  if (audios[other].dataset.id === String(song.id)) active = other
  const audio = audios[active]
  if (audio.dataset.id !== String(song.id)) {
    audio.src = song.url ?? ''
    audio.dataset.id = String(song.id)
  }
  for (const a of audios) if (a !== audio) a.pause()
  currentId = song.id
  if (!song.url) return failed() // e.g. a hi-res DASH manifest: not for browsers
  audio.currentTime = 0
  audio.play().catch((e) => {
    if (e.name === 'NotAllowedError') speaker.error = 'Tap “Start” again: the browser blocked playback'
    failed()
  })
  setState('playing')
  preloadNext()
}

function preloadNext() {
  const next = queue.find((s) => s.id !== currentId && s.url)
  const other = audios[1 - active]
  if (next && other.dataset.id !== String(next.id)) {
    other.src = next.url
    other.dataset.id = String(next.id)
    other.load()
  }
}

function startFirst() {
  const song = queue[0]
  if (song) play(song)
  else setState('stopped')
}

/** The current song is done (ended or skipped): consume it, play the next. */
function advance() {
  queue = queue.filter((s) => s.id !== currentId)
  currentId = null
  startFirst()
}

/** Like Mopidy after a stream error: stop, but keep the song queued. */
function failed() {
  audios[active].pause()
  currentId = null
  setState('stopped')
}

function handle(cmd) {
  switch (cmd.cmd) {
    case 'enqueue':
      queue.push({ id: cmd.id, url: cmd.url ?? null, title: cmd.title, artist: cmd.artist, length_ms: cmd.length_ms })
      preloadNext()
      break
    case 'remove':
      queue = queue.filter((s) => s.id !== cmd.id)
      if (currentId === cmd.id) failed()
      break
    case 'play':
      if (speaker.state === 'paused' && current()) {
        audios[active].play().catch(failed)
        setState('playing')
      } else if (!current()) startFirst()
      break
    case 'next':
      advance()
      break
    case 'pause':
      audios[active].pause()
      if (current()) setState('paused')
      break
    case 'resume':
      if (current()) {
        audios[active].play().catch(failed)
        setState('playing')
      }
      break
  }
  if (cmd.seq) ack = Math.max(ack, cmd.seq)
  report()
}

function report() {
  if (ws?.readyState !== WebSocket.OPEN) return
  const audio = audios[active]
  ws.send(
    JSON.stringify({
      type: 'status',
      state: speaker.state,
      position_ms: current() ? Math.round(audio.currentTime * 1000) : 0,
      current: current() ? currentId : null,
      queue: queue.map((s) => s.id),
      ack,
    }),
  )
}

function connect() {
  clearTimeout(reconnectTimer)
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const token = encodeURIComponent(party.session.token)
  // takeover: the host chose this device, so it replaces any other player.
  ws = new WebSocket(`${proto}://${location.host}${BASE}player/ws?token=${token}&takeover=1`)
  ws.onopen = () => {
    ack = 0 // per connection, like the agent
    retries = 0
    speaker.connected = true
    speaker.error = null
    report()
  }
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data)
    if (msg.cmd) handle(msg)
  }
  ws.onclose = (event) => {
    speaker.connected = false
    ws = null
    if (!speaker.active) return
    if (event.code === 4001) return stop('Only the party’s host can use a device as the speaker')
    if (event.code === 4002) return stop('Another device took over as the speaker')
    reconnectTimer = setTimeout(connect, Math.min(1000 * 2 ** retries++, 15000))
  }
}

async function keepAwake() {
  try {
    wakeLock = await navigator.wakeLock?.request('screen')
  } catch {
    // Not supported or not allowed (e.g. low battery): the page still works.
  }
}

document.addEventListener('visibilitychange', () => {
  if (speaker.active && document.visibilityState === 'visible') keepAwake()
})

/** Must run from a tap: browsers only allow audio after a user gesture. */
export function start() {
  for (const audio of audios) {
    // Unlock both elements now, so later songs may start without a tap.
    audio.muted = true
    audio.play().catch(() => {})
    audio.pause()
    audio.muted = false
    audio.volume = speaker.volume
  }
  speaker.active = true
  speaker.error = null
  keepAwake()
  connect()
  clearInterval(reportTimer)
  reportTimer = setInterval(report, REPORT_EVERY_MS)
}

export function stop(reason = null) {
  speaker.active = false
  speaker.error = reason
  clearInterval(reportTimer)
  clearTimeout(reconnectTimer)
  for (const audio of audios) {
    audio.pause()
    audio.removeAttribute('src')
    delete audio.dataset.id
    audio.load()
  }
  queue = []
  currentId = null
  speaker.state = 'stopped'
  speaker.current = null
  wakeLock?.release?.().catch(() => {})
  wakeLock = null
  if (ws) {
    const socket = ws
    ws = null
    socket.close()
  }
}

export function setVolume(value) {
  speaker.volume = value
  for (const audio of audios) audio.volume = value
}
