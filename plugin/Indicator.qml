import QtQuick
import Quickshell
import qs.Commons
import qs.Ui
import "@PLUGIN_DIR@" as Plugin
import "@PLUGIN_DIR@/Model.js" as Model
import "@PLUGIN_DIR@/I18n.js" as I18n

// predmaxim.yandex-music among the bar's indicators: lit while a track plays
// or is paused. Left click toggles the window (the hidden widget, Panel.qml);
// right click pauses or resumes while a track is audible, otherwise acts like
// left click. keep-custom-widgets.sh copies this file into the
// predmaxim.indicators clone as indicators/YandexMusic.qml and fills in @PLUGIN_DIR@.
BarIndicator {
  id: root

  readonly property var tr: I18n.translator(I18n.textLanguage(function(name) { return Quickshell.env(name) }))
  readonly property var look: Model.view(link.music)

  fontSize: Style.font.body
  active: look.lit
  activeText: look.icon
  inactiveText: look.icon
  activeTooltipText: root.tr(look.tip, look.arg, look.arg2)
  inactiveTooltipText: root.tr(look.tip, look.arg, look.arg2)

  onPressed: function(button) {
    if (button === Qt.RightButton && Model.canToggle(link.music)) {
      link.send(Model.cmd("toggle"))
    } else if (button === Qt.LeftButton || button === Qt.RightButton) {
      Quickshell.execDetached(["omarchy-shell", "predmaxim.yandex-music", "toggle"])
    }
  }

  Plugin.Link { id: link }
}
