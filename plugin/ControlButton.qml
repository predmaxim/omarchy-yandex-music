import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

// A transport / like button by name (Model.control), in the panel's "controls" cursor row;
// enabled only when it has something to act on.
Button {
  id: control
  required property var panel
  property string name
  readonly property int at: panel.controls.indexOf(name)
  readonly property var look: Model.control(name, panel.music)

  iconText: look.icon
  iconSize: Style.font.subtitle * 1.5
  horizontalPadding: Style.space(5)
  verticalPadding: Style.space(2)
  width: Math.max(implicitWidth, implicitHeight)
  height: width
  tooltipText: panel.tr(look.tip)
  hasCursor: panel.row === "controls" && panel.col === at && at >= 0
  enabled: Model.controlEnabled(name, panel.music)
  foreground: enabled ? panel.bar.foreground : Qt.darker(panel.bar.foreground, 1.4)
  fontFamily: panel.bar.fontFamily
  onClicked: panel.activate(name)
  HoverHandler {
    id: hover
    onPointChanged: if (hover.hovered && control.at >= 0) control.panel.hoverCursor(control, hover.point.position, "controls", control.at)
  }
}
