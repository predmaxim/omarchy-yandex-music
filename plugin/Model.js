.pragma library

// ymd's state line -> what the bar icon and the window show, and the command
// lines the plugin writes to ymd's socket.

// Nerd Font glyphs: play, pause, a plain note when nothing plays; prev, next…
var ICONS = {
  playing: String.fromCodePoint(0xF040A),
  paused: String.fromCodePoint(0xF03E4),
  empty: String.fromCodePoint(0xF075A),
  prev: String.fromCodePoint(0xF04AE),
  next: String.fromCodePoint(0xF04AD),
  play: String.fromCodePoint(0xF040A)
}

// Header buttons, in cursor order (Panel.head = index).
var HEAD = ["prev", "toggle", "next", "dislike", "like"]

var MOOD_LABELS = { all: "Any", fun: "Fun", active: "Energetic", calm: "Calm", sad: "Sad" }

var OFFLINE = { running: false, auth: "none", login: null, source: { type: "none", title: "", mood: "" }, moods: [],
  playing: false, track: null, queue: [], index: -1, position: 0, duration: 0, has_more: false, loading: false, search: { text: "", results: [] }, error: null }

function parse(line) {
  var s = null
  try { s = JSON.parse(line) } catch (e) { return null }
  if (!s || typeof s.auth !== "string") return null
  s.running = true
  s.has_more = !!s.has_more
  s.loading = !!s.loading
  return s
}

function cmd(name, args) {
  var o = { cmd: name }
  for (var k in (args || {})) o[k] = args[k]
  return JSON.stringify(o) + "\n"
}

function view(st) {
  if (!st || !st.running) return { lit: false, icon: ICONS.empty, tip: "Music service is not running", arg: "" }
  if (st.auth !== "ok") return { lit: false, icon: ICONS.empty, tip: "Yandex Music: log in needed", arg: "" }
  if (!st.track) return { lit: false, icon: ICONS.empty, tip: "Nothing is playing", arg: "" }
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
  if (st.error) return tr("Error: %1", tr(st.error))
  var parts = [st.track ? st.track.artists : "", sourceName(st.source, tr)].filter(function(p) { return p })
  return parts.join(" · ")
}

function searching(st) { return !!(st.search && st.search.text) }

// pending: a row clicked a moment ago, marked before ymd confirms it.
function rows(st, pending) {
  var cur = pending >= 0 ? pending : st.index
  if (searching(st))
    return st.search.results.map(function(r) {
      return { id: r.id, title: r.title, artists: r.album ? r.artists + " · " + r.album : r.artists, current: false } })
  return st.queue.map(function(r, i) { return { id: r.id, title: r.title, artists: r.artists, current: i === cur } })
}

function moodOptions(st, tr) {
  return (st.moods || []).map(function(m) { return { value: m, label: tr(MOOD_LABELS[m] || m) } })
}

function fmtTime(s) {
  s = Math.max(0, Math.floor(s || 0))
  var r = s % 60
  return Math.floor(s / 60) + ":" + (r < 10 ? "0" : "") + r
}

// Position now: the one from the state line plus the time since (only while playing).
function position(st, elapsedMs) {
  var p = (st.position || 0) + (st.playing ? elapsedMs / 1000 : 0)
  return st.duration > 0 ? Math.min(p, st.duration) : p
}

// Ask for the next page once per list length, when ymd has more and is not busy.
function wantMore(st, shownCount, askedAt) {
  return !!st.has_more && !st.loading && shownCount > 0 && askedAt !== shownCount
}

// Right click on the bar icon pauses/resumes whenever a track is audible.
function canToggle(st) { return !!(st && st.running && st.auth === "ok" && st.track) }
