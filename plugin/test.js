// node test.js
const fs = require("fs")
const assert = require("assert")
const load = (file, names) =>
  new Function(fs.readFileSync(__dirname + "/" + file, "utf8").replace(".pragma library", "") + "; return { " + names + " }")()
const M = load("Model.js", "OFFLINE, ICONS, parse, cmd, view, subtitle, rows, searching, moodOptions, fmtTime, position, wantMore, canToggle, HEAD, syncRows")
const I = load("I18n.js", "TABLES, translator")
const ru = I.translator("ru")

const st = M.parse(JSON.stringify({
  auth: "ok", login: null, source: { type: "wave", title: "", mood: "calm" }, moods: ["all", "fun", "active", "calm", "sad"],
  playing: true, track: { id: "2", title: "Группа крови", artists: "Кино", liked: true, cover: "" },
  queue: [{ id: "1", title: "Звезда", artists: "Кино" }, { id: "2", title: "Группа крови", artists: "Кино" }],
  index: 1, search: { text: "", results: [] }, error: null }))
assert.ok(st)
assert.strictEqual(M.parse("{broken"), null)
assert.strictEqual(M.parse('{"playing":true}'), null)
assert.strictEqual(M.parse(""), null)

// Commands
assert.strictEqual(M.cmd("toggle"), '{"cmd":"toggle"}\n')
assert.deepStrictEqual(JSON.parse(M.cmd("play", { index: 3 })), { cmd: "play", index: 3 })
assert.deepStrictEqual(JSON.parse(M.cmd("wave", { mood: null })), { cmd: "wave", mood: null })

// Indicator: lit while playing or paused with a track; tooltip "artists — title"
const at = p => Object.assign({}, st, p)
assert.deepStrictEqual([M.view(st).lit, M.view(st).icon], [true, M.ICONS.playing])
// Icons: play while playing, pause while paused, plain note when empty (no crossed-out note)
assert.strictEqual(M.ICONS.playing, String.fromCodePoint(0xF040A))
assert.strictEqual(M.ICONS.paused, String.fromCodePoint(0xF03E4))
assert.strictEqual(M.ICONS.empty, String.fromCodePoint(0xF075A))
for (const s of [M.OFFLINE, at({ track: null }), at({ auth: "none", track: null })]) assert.strictEqual(M.view(s).icon, M.ICONS.empty)
assert.deepStrictEqual([M.view(at({ playing: false })).lit, M.view(at({ playing: false })).icon], [true, M.ICONS.paused])
const vv = M.view(st); assert.strictEqual(ru(vv.tip, vv.arg, vv.arg2), "Кино — Группа крови")
assert.strictEqual(M.view(at({ track: null, playing: false })).lit, false)
assert.strictEqual(ru(M.view(M.OFFLINE).tip), "Сервис музыки не запущен")
assert.strictEqual(ru(M.view(at({ auth: "none", track: null })).tip), "Яндекс Музыка: нужен вход")

// Subtitle: artists · source · mood
assert.strictEqual(M.subtitle(st, ru), "Кино · Моя волна · Спокойное")
assert.strictEqual(M.subtitle(at({ source: { type: "likes", title: "", mood: "" } }), ru), "Кино · Мне нравится")
assert.strictEqual(M.subtitle(at({ source: { type: "track-wave", title: "Кукушка", mood: "" } }), ru), "Кино · Волна по треку «Кукушка»")
assert.strictEqual(M.subtitle(at({ source: { type: "search", title: "сплин", mood: "" } }), ru), "Кино · Поиск «сплин»")
assert.strictEqual(M.subtitle(at({ error: "boom" }), ru), "Ошибка: boom")
// The source named is the one the audible track plays from, not the one browsed
assert.strictEqual(M.subtitle(at({ source: { type: "likes", title: "", mood: "" }, play_source: { type: "wave", title: "", mood: "calm" } }), ru), "Кино · Моя волна · Спокойное")
assert.deepStrictEqual(M.OFFLINE.play_source, { type: "none", title: "", mood: "" })

// Rows: queue with the playing one marked; search results while text is typed
assert.deepStrictEqual(M.rows(st).map(r => r.current), [false, true])
assert.deepStrictEqual(M.rows(st, 0).map(r => r.current), [true, false])   // optimistic marker
assert.deepStrictEqual(M.rows(st, -1).map(r => r.current), [false, true])
assert.strictEqual(M.searching(st), false)

// Paging
assert.strictEqual(M.parse('{"auth":"ok"}').has_more, false)
assert.strictEqual(M.parse('{"auth":"ok","has_more":true,"loading":true}').loading, true)
assert.strictEqual(M.wantMore({ has_more: true, loading: false }, 20, -1), true)
assert.strictEqual(M.wantMore({ has_more: true, loading: false }, 20, 20), false)
assert.strictEqual(M.wantMore({ has_more: true, loading: true }, 20, -1), false)
assert.strictEqual(M.wantMore({ has_more: false, loading: false }, 20, -1), false)

// The list model is updated in place (a reassigned model throws the list back to the top)
const fakeModel = () => {
  const m = { rows: [], ops: [] }
  Object.defineProperty(m, "count", { get: () => m.rows.length })
  m.get = i => m.rows[i]
  m.set = (i, r) => { m.ops.push("set " + i); m.rows[i] = Object.assign({}, r) }
  m.append = r => { m.ops.push("append"); m.rows.push(Object.assign({}, r)) }
  m.remove = (i, n) => { m.ops.push("remove " + i + " " + n); m.rows.splice(i, n) }
  return m
}
const page = (n, cur) => Array.from({ length: n }, (_, i) => ({ id: "" + i, title: "t" + i, artists: "a", current: i === cur }))
const lm = fakeModel()
M.syncRows(lm, page(20, 3))
assert.strictEqual(lm.count, 20)
lm.ops = []; M.syncRows(lm, page(40, 3))
assert.deepStrictEqual(lm.ops, Array(20).fill("append"))           // next page: appended, rows above untouched
lm.ops = []; M.syncRows(lm, page(40, 4))
assert.deepStrictEqual(lm.ops, ["set 3", "set 4"])                 // marker moved: two rows changed
lm.ops = []; M.syncRows(lm, page(5, -1))
assert.deepStrictEqual(lm.ops, ["remove 5 35", "set 4"]); assert.deepStrictEqual(lm.rows, page(5, -1))

// Header cursor order and the bar icon's right click
assert.deepStrictEqual(M.HEAD, ["prev", "toggle", "next", "dislike", "like"])
assert.strictEqual(M.canToggle(st), true)
assert.strictEqual(M.canToggle(at({ track: null })), false)
assert.strictEqual(M.canToggle(M.OFFLINE), false)

// Seek bar
assert.deepStrictEqual([0, 5, 65, 3599, 61.9, undefined].map(M.fmtTime), ["0:00", "0:05", "1:05", "59:59", "1:01", "0:00"])
const sp = at({ position: 10, duration: 100 })
assert.strictEqual(M.position(sp, 2500), 12.5)
assert.strictEqual(M.position(at({ position: 10, duration: 100, playing: false }), 2500), 10)
assert.strictEqual(M.position(at({ position: 99, duration: 100 }), 5000), 100)
const ss = at({ search: { text: "сплин", results: [{ id: "9", title: "Орбит", artists: "Сплин", album: "Гранатовый" }] } })
assert.strictEqual(M.searching(ss), true)
assert.deepStrictEqual(M.rows(ss), [{ id: "9", title: "Орбит", artists: "Сплин · Гранатовый", current: false }])

// Mood dropdown: ids from the state, labels translated, "all" first
assert.deepStrictEqual(M.moodOptions(st, ru).map(o => o.label), ["Любое", "Весёлое", "Бодрое", "Спокойное", "Грустное"])

// Every tr("…") has a Russian line
for (const f of ["Panel.qml", "Indicator.qml", "Link.qml", "Model.js"]) {
  if (!fs.existsSync(__dirname + "/" + f)) continue
  for (const m of fs.readFileSync(__dirname + "/" + f, "utf8").matchAll(/\btr\("((?:[^"\\]|\\.)*)"/g))
    assert.ok(Object.prototype.hasOwnProperty.call(I.TABLES.ru, JSON.parse(`"${m[1]}"`)), f + ": no ru for " + m[1])
}
for (const k of Object.values({ a: "Any", b: "Fun", c: "Energetic", d: "Calm", e: "Sad" })) assert.ok(I.TABLES.ru[k], k)

// QML: no own property or id may reuse a built-in name (rules.md §9)
const builtins = ["state", "status", "data", "children", "visible", "enabled", "opacity", "parent", "left", "right", "top", "bottom", "x", "y", "width", "height", "states", "focus", "settings", "opened", "bar"]
for (const f of ["Panel.qml", "Indicator.qml", "Link.qml"]) {
  if (!fs.existsSync(__dirname + "/" + f)) continue
  const src = fs.readFileSync(__dirname + "/" + f, "utf8")
  for (const m of src.matchAll(/^\s*(?:readonly\s+|required\s+)?property\s+\S+\s+(\w+)/gm))
    assert.ok(!builtins.includes(m[1]), f + ": property '" + m[1] + "' shadows a built-in")
  for (const m of src.matchAll(/\bid:\s*(\w+)/g))
    assert.ok(!builtins.includes(m[1]), f + ": id '" + m[1] + "' shadows a built-in")
}

console.log("ok")
