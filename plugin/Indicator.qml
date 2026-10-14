import QtQuick
import Quickshell
import qs.Commons
import qs.Ui
import "@PLUGIN_DIR@" as Plugin
import "@PLUGIN_DIR@/Model.js" as Model
import "@PLUGIN_DIR@/I18n.js" as I18n

// predmaxim.yandex-music among the bar's indicators: a note, lit only while a
// track sounds (hidden like any inactive indicator otherwise); play/pause and
// seek for every player live in predmaxim.media. Click toggles the window (the
// hidden widget, Panel.qml). keep-custom-widgets.sh copies this file into the
// predmaxim.indicators clone as indicators/YandexMusic.qml and fills in @PLUGIN_DIR@.
BarIndicator {
  id: root

  readonly property var tr: I18n.translator(I18n.textLanguage(function(name) { return Quickshell.env(name) }))
  readonly property var look: Model.view(link.music)

  fontSize: Style.font.body
  active: Model.playing(link.music)
  activeText: Model.ICONS.empty
  activeTooltipText: root.tr(look.tip, look.arg, look.arg2)
  inactiveTooltipText: root.tr(look.tip, look.arg, look.arg2)

  onPressed: function(button) {
    if (button === Qt.LeftButton || button === Qt.RightButton)
      Quickshell.execDetached(["omarchy-shell", "predmaxim.yandex-music", "toggle"])
  }

  Plugin.Link { id: link }
}
