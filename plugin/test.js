// node test.js
const fs = require("fs")
const assert = require("assert")
const load = (file, names) =>
  new Function(fs.readFileSync(__dirname + "/" + file, "utf8").replace(".pragma library", "") + "; return { " + names + " }")()
const M = load("Model.js", "OFFLINE, ICONS, parse, cmd, view, subtitle, rows, searching, moodOptions")
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

// Rows: queue with the playing one marked; search results while text is typed
assert.deepStrictEqual(M.rows(st).map(r => r.current), [false, true])
assert.strictEqual(M.searching(st), false)
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
