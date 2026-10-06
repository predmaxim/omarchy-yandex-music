import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

// The My Wave screen under the tabs row: moods, the audible track, seek, buttons. Before the wave
// starts (panel.wave "idle") a placeholder and ▶ stand in the same places. Mood, seek and the
// buttons are cursor rows (panel.row); a mouse over them moves the same cursor.
Column {
  id: wave
  required property var panel
  readonly property var music: panel.music
  readonly property bool playing: panel.wave === "playing"
  readonly property bool audible: playing && panel.hasTrack
  readonly property color fg: panel.bar.foreground
  readonly property color dim: Qt.darker(panel.bar.foreground, 1.4)
  spacing: Style.space(10)

  Words {
    width: parent.width
    panel: wave.panel
    rowName: "mood"
    options: Model.moodOptions(wave.music, wave.panel.tr)
    value: wave.panel.mood
    onPicked: function(v) { wave.panel.pickMood(v) }
  }

  // The track: cover (stock media card), title, artists; before the wave starts: its glyph, name and mood.
  Row {
    x: Style.space(6)
    width: parent.width - x * 2
    spacing: Style.space(14)

    BorderSurface {
      id: art
      width: Style.space(72)
      height: width
      radius: Style.spacing.labelGap
      color: Style.normalFillFor(wave.fg, Color.accent)
      borderSpec: Border.controlSpec("normal", wave.fg, Color.accent)
      Cover {
        id: cover
        anchors.fill: parent
        anchors.margins: Style.space(2)
        visible: wave.playing
        url: wave.playing && wave.music.track ? wave.music.track.cover : ""
      }
      Text {
        anchors.centerIn: parent
        visible: !wave.playing || !cover.ready
        text: Model.ICONS.myWave
        color: wave.dim
        font.family: wave.panel.bar.fontFamily
        font.pixelSize: Style.font.displayLarge
      }
    }

    Column {
      anchors.verticalCenter: parent.verticalCenter
      width: parent.width - art.width - parent.spacing
      spacing: Style.space(4)
      Text {
        width: parent.width
        elide: Text.ElideRight
        textFormat: Text.PlainText
        text: wave.audible && wave.music.track ? wave.music.track.title : wave.panel.tr("My Wave")
        color: wave.audible ? wave.fg : wave.dim
        font.family: wave.panel.bar.fontFamily
        font.pixelSize: Style.font.subtitle
        font.bold: true
      }
      Text {
        width: parent.width
        elide: Text.ElideRight
        textFormat: Text.PlainText
        text: wave.music.error ? Model.subtitle(wave.music, wave.panel.tr)
            : wave.audible && wave.music.track ? wave.music.track.artists
            : Model.moodLabel(wave.panel.mood, wave.panel.tr)
        color: wave.dim
        font.family: wave.panel.bar.fontFamily
        font.pixelSize: Style.font.bodySmall
      }
    }
  }

  // Seek: the slider, elapsed and total under it; disabled before the wave starts.
  CursorSurface {
    id: seekRow
    width: parent.width
    implicitHeight: seek.implicitHeight + times.implicitHeight + Style.space(4) * 2
    hasCursor: wave.panel.row === "seek"
    enabled: wave.audible
    foreground: wave.fg

    PanelSlider {
      id: seek
      x: Style.space(6)
      y: Style.space(4)
      width: parent.width - x * 2
      bar: wave.panel.bar
      fillColor: wave.audible ? wave.fg : wave.dim
      knobColor: fillColor
      minimum: 0
      maximum: Math.max(1, wave.music.duration || 1)
      value: wave.audible ? wave.panel.pos : 0
      onReleased: function(v) { wave.panel.seekTo(v) }
    }
    Item {
      id: times
      anchors.top: seek.bottom
      x: seek.x
      width: seek.width
      implicitHeight: elapsed.implicitHeight
      opacity: wave.audible ? 1 : 0
      Text {
        id: elapsed
        text: Model.fmtTime(seek.dragging ? seek.liveValue : wave.panel.pos)
        color: wave.dim
        font.family: wave.panel.bar.fontFamily
        font.pixelSize: Style.font.caption
      }
      Text {
        anchors.right: parent.right
        text: Model.fmtTime(wave.music.duration)
        color: wave.dim
        font.family: wave.panel.bar.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
    HoverHandler {
      id: seekHover
      onPointChanged: if (seekHover.hovered && wave.audible) wave.panel.hoverCursor(seekRow, seekHover.point.position, "seek", 0)
    }
  }

  // Dislike at the left edge, like at the right, prev · play/pause · next centered; before the wave starts only ▶.
  CursorSurface {
    width: parent.width
    implicitHeight: toggle.height + Style.space(4) * 2
    hasCursor: wave.panel.row === "controls"
    foreground: wave.fg

    ControlButton {
      panel: wave.panel
      name: "dislike"
      visible: wave.playing
      foreground: wave.dim   // the edges stay quiet next to the transport
      anchors.left: parent.left
      anchors.leftMargin: Style.space(4)
      anchors.verticalCenter: parent.verticalCenter
      iconSize: Style.font.heading
    }
    Row {
      anchors.centerIn: parent
      spacing: Style.space(14)
      ControlButton { panel: wave.panel; name: "prev"; visible: wave.playing; anchors.verticalCenter: parent.verticalCenter; iconSize: Style.font.display }
      ControlButton { id: toggle; panel: wave.panel; name: wave.playing ? "toggle" : "start"; anchors.verticalCenter: parent.verticalCenter; iconSize: Style.font.display * 1.4 }
      ControlButton { panel: wave.panel; name: "next"; visible: wave.playing; anchors.verticalCenter: parent.verticalCenter; iconSize: Style.font.display }
    }
    ControlButton {
      panel: wave.panel
      name: "like"
      visible: wave.playing
      foreground: wave.dim   // the edges stay quiet next to the transport
      anchors.right: parent.right
      anchors.rightMargin: Style.space(4)
      anchors.verticalCenter: parent.verticalCenter
      iconSize: Style.font.heading
    }
  }
}
