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

// Header buttons on list tabs, in cursor order.
var HEAD = ["prev", "toggle", "next", "dislike", "like"]
// The My Wave screen's buttons, by view.
var WAVE_CONTROLS = { playing: ["dislike", "prev", "toggle", "next", "like"], idle: ["start"] }
var TABS = ["wave", "likes"]
var MOOD_DELAY = 400   // ms: stepping through moods restarts a playing wave once, after the last step

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

// --- the keyboard cursor: { row, col, cur } -------------------------------------------------
// row: one of cursorRows (or "" for none); col: the item in it (tab, mood, button; on a list row
// 1 is its wave button); cur: the list row. ↑/↓ walk rows, ←/→ the items of a row.

function controlRow(st) { return waveView(st) ? waveControls(st) : HEAD }

// The rows the cursor walks on this screen, top to bottom: My Wave — tabs, mood, seek (while the
// wave plays), buttons; list tabs — tabs, header buttons (while a track is audible), the list.
function cursorRows(st) {
  if (!st || !st.running || st.auth !== "ok") return []
  var wave = waveView(st)
  if (wave) return ["tabs", "mood"].concat(wave === "playing" && canToggle(st) ? ["seek"] : [], ["controls"])
  return ["tabs"].concat(canToggle(st) ? ["controls"] : [], rows(st, -1).length ? ["list"] : [])
}

function rowItems(row, st) {
  return { tabs: TABS.length, mood: (st.moods || []).length, controls: controlRow(st).length, list: 2 }[row] || 0
}

// The mood shown as picked: the one just stepped to (pending, not sent yet) or the wave's.
function shownMood(st, pending) { return pending || (st.source && st.source.mood) || "all" }

// A row as the cursor enters it: on the shown tab / mood, on play/pause (▶ before the wave starts).
function cursorAt(row, st, mood, cur) {
  var col = row === "tabs" ? TABS.indexOf(st.source.type)
          : row === "mood" ? (st.moods || []).indexOf(shownMood(st, mood))
          : row === "controls" ? controlRow(st).indexOf(waveView(st) === "idle" ? "start" : "toggle") : 0
  return { row: row, col: Math.max(0, col), cur: row === "list" ? cur || 0 : -1 }
}

// Where the cursor starts when the window opens: on play/pause (▶ on the idle wave screen);
// with nothing audible on a list tab, on its first row, so Enter does something (plays it).
function initialCursor(st) {
  var r = cursorRows(st)
  if (r.indexOf("controls") >= 0) return cursorAt("controls", st)
  if (r.indexOf("list") >= 0) return cursorAt("list", st, "", 0)
  return r.length ? cursorAt(r[0], st) : { row: "", col: 0, cur: -1 }
}

// ↑/↓ (step -1/1). Without a cursor (just typed): ↓ to the first result, ↑ where the window opens.
function moveCursor(st, c, step, mood) {
  var r = cursorRows(st), count = rows(st, -1).length
  if (c.row === "list" && r.indexOf("list") >= 0 && c.cur + step >= 0) return cursorAt("list", st, mood, Math.min(count - 1, c.cur + step))
  var k = r.indexOf(c.row)
  if (k < 0) return step > 0 && r.indexOf("list") >= 0 ? cursorAt("list", st, mood, 0) : initialCursor(st)
  var next = r[Math.max(0, Math.min(r.length - 1, k + step))]
  return next === c.row ? c : cursorAt(next, st, mood, 0)
}

// ←/→ (dx -1/1) on the cursor's row: { col, tab?, mood? } — a tab or a mood applies at once — or { seek: seconds }:
// 10 s on the seek row (Shift: 30), Shift+←/→ anywhere else 10 s. null: no cursor row.
function sideCursor(st, c, dx, shift, mood) {
  if (c.row === "seek" || (shift && canToggle(st))) return { seek: dx * (c.row === "seek" && shift ? 30 : 10) }
  var n = rowItems(c.row, st)
  if (!n) return null
  var r = { col: Math.max(0, Math.min(n - 1, c.col + dx)) }
  if (c.row === "tabs" && TABS[r.col] !== st.source.type) r.tab = TABS[r.col]
  if (c.row === "mood" && st.moods[r.col] !== shownMood(st, mood)) r.mood = st.moods[r.col]
  return r
}

// The screen changed (another tab, the wave started or stopped): the same row if it is there
// (on the buttons: on play/pause again), else where the window opens.
function screenCursor(st, c) {
  if (!c.row) return c
  if (cursorRows(st).indexOf(c.row) < 0) return initialCursor(st)
  return c.row === "controls" ? cursorAt("controls", st) : c
}

// The mood to send once stepping stopped (MOOD_DELAY): null if it is the wave's already or the wave is gone.
function moodToSend(st, pending) {
  return pending && st.source && st.source.type === "wave" && pending !== shownMood(st, "") ? pending : null
}
