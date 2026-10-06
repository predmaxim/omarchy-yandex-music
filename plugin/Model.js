.pragma library

// ymd's state line -> what the bar icon and the window show, and the command
// lines the plugin writes to ymd's socket.

// Nerd Font (MDI) glyphs: play, pause, a plain note when nothing plays; header buttons; row buttons.
var ICONS = {
  playing: String.fromCodePoint(0xF040A),  // play
  paused: String.fromCodePoint(0xF03E4),   // pause
  empty: String.fromCodePoint(0xF075A),
  prev: String.fromCodePoint(0xF04AE),     // skip_previous
  next: String.fromCodePoint(0xF04AD),     // skip_next
  play: String.fromCodePoint(0xF040A),
  dislike: String.fromCodePoint(0xF0512),  // thumb_down_outline
  like: String.fromCodePoint(0xF02D5),     // heart_outline
  liked: String.fromCodePoint(0xF02D1),    // heart
  wave: String.fromCodePoint(0xF0411),     // playlist_play
  myWave: String.fromCodePoint(0xF0388)    // the My Wave screen before the wave starts
}

// Header buttons, in cursor order (Panel.head = index).
var HEAD = ["prev", "toggle", "next", "dislike", "like"]
// The My Wave screen: its buttons by view, and the source row above them.
var WAVE_CONTROLS = { playing: ["dislike", "prev", "toggle", "next", "like"], idle: ["start"] }
var SOURCE_ROW = ["wave", "likes", "mood"]

var MOOD_LABELS = { all: "Any", fun: "Fun", active: "Energetic", calm: "Calm", sad: "Sad" }

var OFFLINE = { running: false, auth: "none", login: null, source: { type: "none", title: "", mood: "" },
  play_source: { type: "none", title: "", mood: "" }, moods: [],
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

function moodLabel(mood, tr) { return tr(MOOD_LABELS[mood || "all"] || mood) }

function sourceName(src, tr) {
  if (src.type === "wave") return tr("My Wave") + (src.mood && src.mood !== "all" ? " · " + moodLabel(src.mood, tr) : "")
  if (src.type === "likes") return tr("Liked")
  if (src.type === "track-wave") return tr("Wave by track «%1»", src.title)
  if (src.type === "search") return tr("Search «%1»", src.title)
  return ""
}

function subtitle(st, tr) {
  if (st.error) return tr("Error: %1", tr(st.error))
  var parts = [st.track ? st.track.artists : "", sourceName(st.play_source || st.source, tr)].filter(function(p) { return p })
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

// Bring a ListModel to `rows` in place: changed rows set, a new page appended, extra rows
// removed. Reassigning the model would throw the list back to the top.
function syncRows(model, rows) {
  if (model.count > rows.length) model.remove(rows.length, model.count - rows.length)
  for (var i = 0; i < rows.length; i++) {
    var r = rows[i], o = i < model.count ? model.get(i) : null
    if (!o) model.append(r)
    else if (Object.keys(r).some(function(k) { return o[k] !== r[k] })) model.set(i, r)
  }
}

function moodOptions(st, tr) {
  return (st.moods || []).map(function(m) { return { value: m, label: tr(MOOD_LABELS[m] || m) } })
}

function fmtTime(s) {
  s = Math.max(0, Math.floor(s || 0))
  var r = s % 60
  return Math.floor(s / 60) + ":" + (r < 10 ? "0" : "") + r
}

// Position now: the one from the state line plus the time since (only while playing); 0 until the length is known.
function position(st, elapsedMs) {
  var p = (st.position || 0) + (st.playing ? elapsedMs / 1000 : 0)
  return st.duration > 0 ? Math.min(p, st.duration) : 0
}

// Ask for the next page once per list length, when ymd has more and is not busy.
function wantMore(st, shownCount, askedAt) {
  return !!st.has_more && !st.loading && shownCount > 0 && askedAt !== shownCount
}

// Right click on the bar icon pauses/resumes whenever a track is audible.
function canToggle(st) { return !!(st && st.running && st.auth === "ok" && st.track) }

// My Wave screen: "playing" while the wave is the play source, "idle" before it starts; null on other lists.
function waveView(st) {
  if (!st || st.auth !== "ok" || !st.source || st.source.type !== "wave" || searching(st)) return null
  return st.play_source && st.play_source.type === "wave" ? "playing" : "idle"
}

function waveControls(st) { return WAVE_CONTROLS[waveView(st)] || [] }

// A header / wave button: "start" plays the browsed wave from its first track (it becomes the play source).
function controlCmd(name) { return name === "start" ? cmd("play", { index: 0 }) : cmd(name) }

// Enabled while a track is audible; ▶ (start the wave) always.
function controlEnabled(name, st) { return name === "start" || canToggle(st) }

function control(name, st) {
  if (name === "toggle") return st.playing ? { icon: ICONS.paused, tip: "Pause" } : { icon: ICONS.play, tip: "Play" }
  if (name === "like") return { icon: st.track && st.track.liked ? ICONS.liked : ICONS.like, tip: "Like" }
  return { prev: { icon: ICONS.prev, tip: "Previous" }, next: { icon: ICONS.next, tip: "Next" },
           dislike: { icon: ICONS.dislike, tip: "Dislike" }, start: { icon: ICONS.play, tip: "Play" } }[name]
}

// Mood for the Wave chip: the wave that plays (or is browsed) again, not a restart as "any".
function waveMood(st) {
  var w = [st.play_source, st.source].filter(function(s) { return s && s.type === "wave" })[0]
  return w ? w.mood : "all"
}
