.pragma library
// Interface text in other languages, keyed by the English text itself (the
// agent-speak / todo scheme): a string missing from a table shows in English.
var TABLES = {
  ru: {
    "Yandex Music": "Яндекс Музыка",
    "%1 — %2": "%1 — %2",
    "Music service is not running": "Сервис музыки не запущен",
    "Yandex Music: log in needed": "Яндекс Музыка: нужен вход",
    "Not logged in": "Не выполнен вход",
    "Search…": "Поиск…",
    "Wave": "Волна", "Liked": "Мне нравится",
    "My Wave": "Моя волна", "Wave by track «%1»": "Волна по треку «%1»", "Search «%1»": "Поиск «%1»",
    "Error: %1": "Ошибка: %1",
    "Any": "Любое", "Fun": "Весёлое", "Energetic": "Бодрое", "Calm": "Спокойное", "Sad": "Грустное",
    "Like": "Нравится", "Dislike": "Не нравится", "Wave by this track": "Волна по треку",
    "Log in": "Войти",
    "Open ya.ru/device and enter the code, or scan the QR code with your phone": "Откройте ya.ru/device и введите код или отсканируйте QR телефоном",
    "Waiting for confirmation…": "Жду подтверждения…",
    "Nothing found": "Ничего не найдено",
    "Nothing is playing": "Ничего не играет"
  }
}

function textLanguage(env) {
  var names = ["LC_ALL", "LC_MESSAGES", "LANG"]
  for (var i = 0; i < names.length; i++) {
    var v = String(env(names[i]) || "").split(".")[0].split("@")[0]
    if (v && v !== "C" && v !== "POSIX") {
      var l = v.slice(0, 2).toLowerCase()
      return TABLES[l] ? l : "en"
    }
  }
  return "en"
}

function translator(lang) {
  var table = TABLES[lang] || {}
  return function(text) {
    var out = Object.prototype.hasOwnProperty.call(table, text) ? table[text] : text
    for (var i = 1; i < arguments.length; i++) out = out.split("%" + i).join(String(arguments[i]))
    return out
  }
}
