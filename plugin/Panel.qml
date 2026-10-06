import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import qs.Ui
import "."
import "Model.js" as Model
import "I18n.js" as I18n

// predmaxim.yandex-music: the window of ymd. The bar icon is Indicator.qml in
// the predmaxim.indicators clone; this widget stays in the layout hidden, for
// the IPC toggle. Everything shown comes from ymd's state line; clicks send
// commands and the window shows what ymd confirms.
Panel {
  id: root
  moduleName: "predmaxim.yandex-music"
  ipcTarget: "predmaxim.yandex-music"

  readonly property var tr: I18n.translator(I18n.textLanguage(function(name) { return Quickshell.env(name) }))
  readonly property var music: link.music
  readonly property var shown: Model.rows(root.music)
  readonly property bool loggedIn: root.music.running && root.music.auth === "ok"

  property int cur: -1
  property bool btnFocus: false
  property int head: -1

  visible: false
  implicitWidth: 0
  implicitHeight: 0

  function send(name, args) { link.send(Model.cmd(name, args)) }

  function moveRow(step) {
    root.btnFocus = false
    if (root.head >= 0) { if (step > 0) { root.head = -1; root.cur = 0 } ; return }
    var i = root.cur + step
    if (i < 0) { root.cur = -1; root.head = 1; return }
    root.cur = Math.min(root.shown.length - 1, i)
    moveGate.reset()
    list.positionViewAtIndex(root.cur, ListView.Contain)
  }

  function side(dx, event) {
    if (root.head >= 0) { root.head = Math.max(0, Math.min(1, root.head + dx)); return }
    if (root.cur >= 0) { root.btnFocus = dx > 0; return }
    event.accepted = false
  }

  function enter(event) {
    if (root.head === 0) root.send("dislike")
    else if (root.head === 1) root.send("like")
    else if (root.cur >= 0 && root.btnFocus) root.waveFrom(root.cur)
    else if (root.cur >= 0) root.playRow(root.cur)
    else event.accepted = false
  }

  function playRow(i) {
    if (Model.searching(root.music)) { root.send("play-search", { index: i }); field.text = "" }
    else root.send("play", { index: i })
  }

  function waveFrom(i) {
    root.send("wave-track", { id: root.shown[i].id })
    field.text = ""
  }

  onShownChanged: if (root.cur >= root.shown.length) root.cur = root.shown.length - 1

  onOpenedChanged: {
    if (opened) {
      cur = -1; head = -1; btnFocus = false
      moveGate.reset()
      Qt.callLater(function() { field.forceActiveFocus() })
    }
  }

  PointerMoveGate { id: moveGate; referenceItem: card }
  Link { id: link; wanted: root.opened }

  // Search waits for a pause in typing.
  Timer {
    id: searchDelay
    interval: 300
    onTriggered: root.send("search", { text: field.text })
  }

  PanelWindow {
    id: modal
    screen: root.QsWindow.window ? root.QsWindow.window.screen : null
    visible: root.opened
    color: Color.menu.scrim
    exclusionMode: ExclusionMode.Ignore
    anchors { top: true; bottom: true; left: true; right: true }
    WlrLayershell.namespace: "predmaxim-yandex-music"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: visible ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None

    MouseArea { anchors.fill: parent; onClicked: root.close() }

    BorderSurface {
      id: card
      anchors.centerIn: parent
      width: Math.min(Style.space(520), modal.width - Style.space(80))
      height: Math.min(column.implicitHeight + card.contentTopInset + card.contentBottomInset, modal.height * 0.85)
      color: Color.popups.background
      borderSpec: Border.surfaceSpec("popups", "border", Color.popups.border, Math.max(1, Style.space(2)))
      padding: Style.spacing.panelPadding
      radius: Style.cornerRadius

      MouseArea { anchors.fill: parent }

      Column {
        id: column
        anchors.fill: parent
        anchors.topMargin: card.contentTopInset
        anchors.rightMargin: card.contentRightInset
        anchors.bottomMargin: card.contentBottomInset
        anchors.leftMargin: card.contentLeftInset
        spacing: Style.space(14)

        PanelHero {
          title: root.music.track ? root.music.track.title : root.tr("Yandex Music")
          meta: !root.music.running ? root.tr("Music service is not running")
              : root.music.auth !== "ok" ? root.tr("Not logged in")
              : root.music.track ? Model.subtitle(root.music, root.tr) : root.tr("Nothing is playing")
          foreground: root.bar.foreground
          fontFamily: root.bar.fontFamily
          iconComponent: Item {
            implicitWidth: Style.space(56); implicitHeight: Style.space(56)
            Image {
              anchors.fill: parent
              visible: !!(root.music.track && root.music.track.cover)
              source: root.music.track ? root.music.track.cover : ""
              fillMode: Image.PreserveAspectCrop
            }
            Text {
              anchors.centerIn: parent
              visible: !(root.music.track && root.music.track.cover)
              text: Model.view(root.music).icon
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.display
            }
          }
          trailingControl: Row {
            visible: root.loggedIn && !!root.music.track
            spacing: Style.space(10)
            Repeater {
              model: [{ icon: "\u{F0514}", tip: "Dislike", cmd: "dislike" },
                      { icon: root.music.track && root.music.track.liked ? "\u{F02D1}" : "\u{F02D5}", tip: "Like", cmd: "like" }]
              Button {
                required property var modelData
                required property int index
                anchors.verticalCenter: parent.verticalCenter
                iconText: modelData.icon
                iconSize: Style.font.subtitle * 1.5
                horizontalPadding: Style.space(5)
                verticalPadding: Style.space(2)
                width: Math.max(implicitWidth, implicitHeight)
                height: width
                tooltipText: root.tr(modelData.tip)
                hasCursor: root.head === index
                foreground: root.bar.foreground
                fontFamily: root.bar.fontFamily
                onClicked: root.send(modelData.cmd)
              }
            }
          }
        }

        PanelSeparator { foreground: root.bar.foreground }

        // No daemon
        Text {
          visible: !root.music.running
          textFormat: Text.PlainText
          text: "systemctl --user start ymd"
          color: Qt.darker(root.bar.foreground, 1.4)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
        }

        // Log in: code and QR
        Column {
          visible: root.music.running && root.music.auth !== "ok"
          width: parent.width
          spacing: Style.space(10)
          Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            textFormat: Text.PlainText
            text: root.tr("Open ya.ru/device and enter the code, or scan the QR code with your phone")
            color: Qt.darker(root.bar.foreground, 1.4)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.body
            visible: !!root.music.login
          }
          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: !!root.music.login
            textFormat: Text.PlainText
            text: root.music.login ? root.music.login.code : ""
            color: root.bar.foreground
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.displayLarge
            font.bold: true
            font.letterSpacing: 6
          }
          Image {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: !!(root.music.login && root.music.login.qr)
            source: root.music.login && root.music.login.qr ? "file://" + root.music.login.qr : ""
            cache: false
            width: Style.space(160); height: width
            smooth: false
          }
          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: root.music.auth === "pending"
            textFormat: Text.PlainText
            text: root.tr("Waiting for confirmation…")
            color: Qt.darker(root.bar.foreground, 1.4)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
          }
          Button {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: root.music.auth === "none"
            bordered: true
            text: root.tr("Log in")
            foreground: root.bar.foreground
            fontFamily: root.bar.fontFamily
            onClicked: root.send("login")
          }
        }

        // Search: borderless, like todo; always holds the keyboard.
        TextField {
          id: field
          visible: root.loggedIn
          width: parent.width
          height: Math.max(Style.space(34), Style.font.title + Style.spacing.controlPaddingY * 2)
          leftPadding: 0; rightPadding: 0; topPadding: 0; bottomPadding: 0
          background: null
          placeholderText: root.tr("Search…")
          placeholderTextColor: Util.alpha(root.bar.foreground, 0.58)
          foreground: root.bar.foreground
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.heading
          cursorDelegate: Item {}
          onTextEdited: { root.cur = -1; root.head = -1; searchDelay.restart() }
          onTextChanged: if (text === "") { searchDelay.stop(); root.send("search", { text: "" }) }
          Keys.onUpPressed: root.moveRow(-1)
          Keys.onDownPressed: root.moveRow(1)
          Keys.onLeftPressed: function(event) { root.side(-1, event) }
          Keys.onRightPressed: function(event) { root.side(1, event) }
          Keys.onReturnPressed: function(event) { root.enter(event) }
          Keys.onEnterPressed: function(event) { root.enter(event) }
          Keys.onSpacePressed: function(event) {
            if (text === "") root.send("toggle")
            else event.accepted = false
          }
          Keys.onEscapePressed: { if (text !== "") text = ""; else root.close() }
          Keys.onPressed: function(event) {
            if (!(event.modifiers & Qt.ControlModifier)) return
            if (event.key === Qt.Key_L) { root.send("like"); event.accepted = true }
            else if (event.key === Qt.Key_D) { root.send("dislike"); event.accepted = true }
          }
        }

        // Source: Wave / Liked + mood (only for My Wave); hidden while searching.
        Row {
          visible: root.loggedIn && !Model.searching(root.music)
          spacing: Style.space(10)
          ButtonGroup {
            options: [{ value: "wave", label: root.tr("Wave") }, { value: "likes", label: root.tr("Liked") }]
            value: root.music.source.type === "wave" || root.music.source.type === "likes" ? root.music.source.type : ""
            focusable: false
            foreground: root.bar.foreground
            fontFamily: root.bar.fontFamily
            onChanged: function(v) { if (v === "wave") root.send("wave", { mood: null }); else root.send("playlist") }
          }
          Dropdown {
            visible: root.music.source.type === "wave"
            width: Style.spacing.dropdownWidth
            showLabel: false
            options: Model.moodOptions(root.music, root.tr)
            value: root.music.source.mood || "all"
            foreground: root.bar.foreground
            fontFamily: root.bar.fontFamily
            onChanged: function(v) { if (v !== (root.music.source.mood || "all")) root.send("wave", { mood: v }) }
          }
        }

        Text {
          visible: root.loggedIn && Model.searching(root.music) && root.shown.length === 0
          textFormat: Text.PlainText
          text: root.tr("Nothing found")
          color: Qt.darker(root.bar.foreground, 1.4)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.body
        }

        ListView {
          id: list
          visible: root.loggedIn
          width: parent.width
          height: Math.min(contentHeight, modal.height * 0.55)
          clip: true
          spacing: Style.spacing.xs
          boundsBehavior: Flickable.StopAtBounds
          model: root.shown

          delegate: CursorSurface {
            id: row
            required property var modelData
            required property int index
            width: list.width
            implicitHeight: Math.max(Style.space(50), texts.implicitHeight + Style.spacing.rowPaddingX * 2)
            foreground: root.bar.foreground
            hasCursor: root.cur === index && !root.btnFocus

            MouseArea {
              id: rowArea
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onPositionChanged: function(mouse) {
                if (moveGate.moved(rowArea, mouse)) { root.head = -1; root.cur = row.index; root.btnFocus = false }
              }
              onClicked: root.playRow(row.index)
            }

            Text {
              id: mark
              anchors.left: parent.left
              anchors.leftMargin: Style.space(12)
              anchors.verticalCenter: parent.verticalCenter
              width: Style.space(20)
              text: row.modelData.current ? "\u{F040A}" : ""
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.body
            }

            Column {
              id: texts
              anchors.left: mark.right
              anchors.leftMargin: Style.space(8)
              anchors.right: waveButton.left
              anchors.rightMargin: Style.space(8)
              anchors.verticalCenter: parent.verticalCenter
              Text {
                width: parent.width
                elide: Text.ElideRight
                textFormat: Text.PlainText
                text: row.modelData.title
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.body
                font.bold: row.modelData.current
              }
              Text {
                width: parent.width
                elide: Text.ElideRight
                textFormat: Text.PlainText
                text: row.modelData.artists
                color: Qt.darker(root.bar.foreground, 1.4)
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
              }
            }

            Button {
              id: waveButton
              anchors.right: parent.right
              anchors.rightMargin: Style.space(8)
              anchors.verticalCenter: parent.verticalCenter
              iconText: "\u{F0411}"
              iconSize: Style.font.subtitle * 1.2
              horizontalPadding: Style.space(4)
              verticalPadding: Style.space(2)
              width: Math.max(implicitWidth, implicitHeight)
              height: width
              tooltipText: root.tr("Wave by this track")
              hasCursor: root.cur === row.index && root.btnFocus
              foreground: root.cur === row.index ? root.bar.foreground : Qt.darker(root.bar.foreground, 1.4)
              fontFamily: root.bar.fontFamily
              onClicked: root.waveFrom(row.index)
            }
          }
        }
      }
    }
  }
}
