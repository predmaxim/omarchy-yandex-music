import QtQuick
import Quickshell
import Quickshell.Io
import "Model.js" as Model

// The connection to ymd: subscribes on connect and keeps the latest state line
// in `music`; commands go out with send(). No daemon (or it restarted) —
// `music` is Model.OFFLINE and a retry runs every 5 s.
// Shared by Indicator.qml (in the predmaxim.indicators clone) and Panel.qml.
Item {
  id: link

  property bool wanted: true
  property var music: Model.OFFLINE
  property bool up: false
  property int attempt: 0      // a failed Socket never reconnects, so each retry builds a new one

  function send(line) {
    if (up && sockLoader.item) {
      sockLoader.item.write(line)
      sockLoader.item.flush()
    }
  }

  visible: false
  onWantedChanged: if (!wanted) { up = false; music = Model.OFFLINE }

  Loader {
    id: sockLoader
    active: link.wanted
    sourceComponent: sockComponent
    property int generation: link.attempt
    onGenerationChanged: { active = false; active = link.wanted }
  }

  Component {
    id: sockComponent
    Socket {
      path: Quickshell.env("XDG_RUNTIME_DIR") + "/ymd.sock"
      connected: true
      onConnectedChanged: {
        link.up = connected
        if (connected) { write(Model.cmd("subscribe")); flush() }
        else link.music = Model.OFFLINE
      }
      parser: SplitParser {
        onRead: function(line) {
          var s = Model.parse(line)
          if (s) link.music = s
        }
      }
    }
  }

  Timer {
    interval: 5000
    repeat: true
    running: link.wanted && !link.up
    onTriggered: link.attempt++
  }
}
