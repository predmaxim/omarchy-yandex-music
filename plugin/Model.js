.pragma library

// ymd's state line -> what the bar icon and the window show, and the command
// lines the plugin writes to ymd's socket.

// Nerd Font glyphs: music, pause, music-off, account-key.
var ICONS = {
  playing: String.fromCodePoint(0xF075A),
  paused: String.fromCodePoint(0xF03E4),
  off: String.fromCodePoint(0xF075B),
  login: String.fromCodePoint(0xF0306)
}

var MOOD_LABELS = { all: "Any", fun: "Fun", active: "Energetic", calm: "Calm", sad: "Sad" }

var OFFLINE = { running: false, auth: "none", login: null, source: { type: "none", title: "", mood: "" }, moods: [],
  playing: false, track: null, queue: [], index: -1, search: { text: "", results: [] }, error: null }

function parse(line) {
  var s = null
  try { s = JSON.parse(line) } catch (e) { return null }
  if (!s || typeof s.auth !== "string") return null
  s.running = true
  return s
}

function cmd(name, args) {
  var o = { cmd: name }
  for (var k in (args || {})) o[k] = args[k]
  return JSON.stringify(o) + "\n"
}

function view(st) {
  if (!st || !st.running) return { lit: false, icon: ICONS.off, tip: "Music service is not running", arg: "" }
  if (st.auth !== "ok") return { lit: false, icon: ICONS.login, tip: "Yandex Music: log in needed", arg: "" }
  if (!st.track) return { lit: false, icon: ICONS.off, tip: "Nothing is playing", arg: "" }
  return { lit: true, icon: st.playing ? ICONS.playing : ICONS.paused, tip: "%1 — %2", arg: st.track.artists, arg2: st.track.title }
}

function sourceName(src, tr) {
  if (src.type === "wave") return tr("My Wave") + (src.mood && src.mood !== "all" ? " · " + tr(MOOD_LABELS[src.mood] || src.mood) : "")
  if (src.type === "likes") return tr("Liked")
  if (src.type === "track-wave") return tr("Wave by track «%1»", src.title)
  if (src.type === "search") return tr("Search «%1»", src.title)
  return ""
}

function subtitle(st, tr) {
  if (st.error) return tr("Error: %1", st.error)
  var parts = [st.track ? st.track.artists : "", sourceName(st.source, tr)].filter(function(p) { return p })
  return parts.join(" · ")
}

function searching(st) { return !!(st.search && st.search.text) }

function rows(st) {
  if (searching(st))
    return st.search.results.map(function(r) {
      return { id: r.id, title: r.title, artists: r.album ? r.artists + " · " + r.album : r.artists, current: false } })
  return st.queue.map(function(r, i) { return { id: r.id, title: r.title, artists: r.artists, current: i === st.index } })
}

function moodOptions(st, tr) {
  return (st.moods || []).map(function(m) { return { value: m, label: tr(MOOD_LABELS[m] || m) } })
}
