import QtQuick
import qs.Commons
import qs.Ui

// A cursor row of words (tabs, moods): the picked one bold, the others dimmed. The whole row lights
// up while it is panel.row; the word under the cursor (keyboard or mouse, one property) gets the
// stock item cursor.
CursorSurface {
  id: words
  required property var panel
  property string rowName
  property var options: []      // [{ value, label }]
  property string value         // the picked one
  readonly property real wordsWidth: line.implicitWidth + line.x
  signal picked(string value)

  implicitHeight: line.implicitHeight + Style.space(4) * 2
  hasCursor: panel.row === rowName
  foreground: panel.bar.foreground

  Row {
    id: line
    x: Style.space(4)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(2)

    Repeater {
      model: words.options
      CursorSurface {
        id: word
        required property var modelData
        required property int index
        readonly property bool chosen: modelData.value === words.value
        implicitWidth: label.implicitWidth + Style.space(8) * 2
        implicitHeight: label.implicitHeight + Style.space(3) * 2
        hasCursor: words.panel.row === words.rowName && words.panel.col === index
        foreground: words.panel.bar.foreground

        Text {
          id: label
          anchors.centerIn: parent
          textFormat: Text.PlainText
          text: word.modelData.label
          color: word.chosen ? words.panel.bar.foreground : Qt.darker(words.panel.bar.foreground, 1.4)
          font.family: words.panel.bar.fontFamily
          font.pixelSize: Style.font.body
          font.bold: word.chosen
        }
        MouseArea {
          id: area
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onPositionChanged: function(mouse) { words.panel.hoverCursor(area, mouse, words.rowName, word.index) }
          onClicked: words.picked(word.modelData.value)
        }
      }
    }
  }
}
