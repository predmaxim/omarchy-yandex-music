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
  // The rows as an array; the list shows them through rowsModel, updated in place so it keeps its scroll.
  property var shown: []
  property string shownSig: ""
  readonly property bool loggedIn: root.music.running && root.music.auth === "ok"
  readonly property bool hasTrack: root.loggedIn && !!root.music.track
  readonly property real listSpace: modal.height * 0.55   // the most the list may take

  property int cur: -1
  property bool btnFocus: false
  property int head: -1
  property int askedAt: -1        // list length at the last "more" request
  property string sourceSig: ""
  property int seenIndex: -1
  property int pendingIndex: -1   // row clicked, shown as current until ymd confirms
  property real pos: 0            // seek bar position, interpolated between state lines
  property real posStamp: 0

  visible: false
  implicitWidth: 0
  implicitHeight: 0

  function send(name, args) { link.send(Model.cmd(name, args)) }

  function refreshRows() {
    var r = Model.rows(root.music, root.pendingIndex)
    var sig = JSON.stringify(r)
    if (sig !== root.shownSig) { root.shownSig = sig; Model.syncRows(rowsModel, r); root.shown = r }
  }
  onMusicChanged: {
    var sig = JSON.stringify(root.music.source) + (root.music.search ? root.music.search.text : "")
    if (sig !== root.sourceSig) {   // another list: start it from the top
      root.sourceSig = sig; root.askedAt = -1
      Qt.callLater(function() { list.positionViewAtBeginning() })
    }
    if (root.pendingIndex >= 0 && root.music.index !== root.seenIndex) root.pendingIndex = -1   // ymd answered
    root.seenIndex = root.music.index
    root.pos = root.music.position || 0
    root.posStamp = Date.now()
    refreshRows()
  }
  onPendingIndexChanged: refreshRows()

  function requestMore() {
    if (!root.opened || !Model.wantMore(root.music, root.shown.length, root.askedAt)) return
    root.askedAt = root.shown.length
    root.send("more")
  }

  function seekTo(s) {
    var d = root.music.duration || 0
    s = Math.max(0, d > 0 ? Math.min(s, d) : s)
    root.send("seek", { seconds: s })
    root.pos = s; root.posStamp = Date.now()
  }
  Component.onCompleted: refreshRows()

  function focusInput() {
    if (root.loggedIn) field.forceActiveFocus()
    else holder.forceActiveFocus()
  }

  function moveRow(step) {
    root.btnFocus = false
    if (root.head >= 0) {
      if (step > 0 && root.shown.length > 0) { root.head = -1; root.cur = 0; moveGate.reset(); list.positionViewAtIndex(0, ListView.Contain) }
      return
    }
    var i = root.cur + step
    if (i < 0) { if (root.hasTrack) { root.cur = -1; root.head = 1 } return }
    if (root.shown.length === 0) return
    root.cur = Math.min(root.shown.length - 1, i)
    if (root.cur >= root.shown.length - 1) root.requestMore()
    moveGate.reset()
    list.positionViewAtIndex(root.cur, ListView.Contain)
  }

  function side(dx, event) {
    if ((event.modifiers & Qt.ShiftModifier) && root.hasTrack) { root.seekTo(root.pos + dx * 10); return }
    if (root.head >= 0) { root.head = Math.max(0, Math.min(Model.HEAD.length - 1, root.head + dx)); return }
    if (root.cur >= 0) { root.btnFocus = dx > 0; return }
    event.accepted = false
  }

  function enter(event) {
    var inList = root.cur >= 0 && root.cur < root.shown.length
    if (root.head >= 0) { if (root.hasTrack) root.send(Model.HEAD[root.head]) }
    else if (inList && root.btnFocus) root.waveFrom(root.cur)
    else if (inList) root.playRow(root.cur)
    else event.accepted = false
  }

  function playRow(i) {
    if (i < 0 || i >= root.shown.length) return
    if (Model.searching(root.music)) { root.send("play-search", { index: i }); field.text = "" }
    else { root.send("play", { index: i }); root.pendingIndex = i; pendingClear.restart() }
    root.cur = -1; root.btnFocus = false
  }

  function waveFrom(i) {
    if (i < 0 || i >= root.shown.length) return
    root.send("wave-track", { id: root.shown[i].id })
    field.text = ""
    root.cur = -1; root.btnFocus = false
  }

  onShownChanged: {
    if (root.shown.length === 0) { root.cur = -1; root.btnFocus = false }
    else if (root.cur >= root.shown.length) root.cur = root.shown.length - 1
    if (root.cur >= 0) Qt.callLater(function() { list.positionViewAtIndex(root.cur, ListView.Contain) })
  }
  onHasTrackChanged: if (!root.hasTrack) root.head = -1
  onLoggedInChanged: Qt.callLater(root.focusInput)

  onOpenedChanged: {
    if (opened) {
      cur = -1; head = -1; btnFocus = false
      moveGate.reset()
      Qt.callLater(function() { if (list.contentHeight < root.listSpace) root.requestMore() })
      Qt.callLater(root.focusInput)
    }
  }

  PointerMoveGate { id: moveGate; referenceItem: card }
  ListModel { id: rowsModel }
  Link { id: link; wanted: root.opened }

  Timer { id: pendingClear; interval: 3000; onTriggered: root.pendingIndex = -1 }

  Timer {
    interval: 500
    repeat: true
    running: root.opened && root.hasTrack && root.music.playing
    onTriggered: root.pos = Model.position(root.music, Date.now() - root.posStamp)
  }

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

    // Keys while the search field is hidden (login screen, no daemon).
    Item {
      id: holder
      Keys.onEscapePressed: root.close()
      Keys.onReturnPressed: if (root.music.running && root.music.auth === "none") root.send("login")
      Keys.onEnterPressed: if (root.music.running && root.music.auth === "none") root.send("login")
    }

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
              model: [{ icon: Model.ICONS.prev, tip: "Previous", cmd: "prev" },
                      { icon: root.music.playing ? Model.ICONS.paused : Model.ICONS.play,
                        tip: root.music.playing ? "Pause" : "Play", cmd: "toggle" },
                      { icon: Model.ICONS.next, tip: "Next", cmd: "next" },
                      { icon: "\u{F0514}", tip: "Dislike", cmd: "dislike" },
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

        // Seek bar: only with a track loaded
        Row {
          visible: root.hasTrack && root.music.duration > 0
          width: parent.width
          spacing: Style.space(8)
          Text {
            id: elapsed
            anchors.verticalCenter: parent.verticalCenter
            width: Style.space(40)
            horizontalAlignment: Text.AlignRight
            text: Model.fmtTime(seek.dragging ? seek.liveValue : root.pos)
            color: Qt.darker(root.bar.foreground, 1.4)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
          }
          PanelSlider {
            id: seek
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - elapsed.width - total.width - parent.spacing * 2
            bar: root.bar
            minimum: 0
            maximum: Math.max(1, root.music.duration || 1)
            value: root.pos
            onReleased: function(v) { root.seekTo(v) }
          }
          Text {
            id: total
            anchors.verticalCenter: parent.verticalCenter
            width: Style.space(40)
            text: Model.fmtTime(root.music.duration)
            color: Qt.darker(root.bar.foreground, 1.4)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
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
            if (!(event.modifiers & Qt.ControlModifier) || !root.hasTrack) return
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
            onChanged: function(v) { if (v === "wave") root.send("wave", { mood: "all" }); else root.send("playlist") }
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

        // Skeleton rows while the first page loads: the window keeps its size.
        Column {
          id: skeleton
          visible: root.loggedIn && root.music.loading && root.shown.length === 0
          width: parent.width
          height: root.listSpace
          spacing: Style.spacing.xs
          clip: true
          Repeater {
            model: 8
            Item {
              id: bone
              required property int index
              width: skeleton.width
              height: Math.max(Style.space(50), (Style.font.body + Style.font.caption) * 1.3 + Style.spacing.rowPaddingX * 2)
              Column {
                anchors.left: parent.left
                anchors.leftMargin: Style.space(40)   // where a row's title starts
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(6)
                Repeater {
                  model: [[Style.font.body, [0.55, 0.4, 0.65, 0.35]], [Style.font.caption, [0.3, 0.22, 0.36, 0.26]]]
                  Rectangle {
                    required property var modelData
                    width: skeleton.width * modelData[1][bone.index % 4]
                    height: modelData[0] * 0.8
                    radius: height / 2
                    color: Qt.darker(root.bar.foreground, 1.4)
                    opacity: 0.25
                  }
                }
              }
            }
          }
        }

        ListView {
          id: list
          visible: root.loggedIn && !skeleton.visible
          width: parent.width
          height: root.listSpace   // fixed: the window does not jump while lists load
          clip: true
          spacing: Style.spacing.xs
          boundsBehavior: Flickable.StopAtBounds
          model: rowsModel
          onContentYChanged: if (contentHeight - contentY - height < height * 0.5) root.requestMore()
          onContentHeightChanged: if (contentHeight < root.listSpace) root.requestMore()   // list too short to scroll

          delegate: CursorSurface {
            id: row
            required property var model
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
              text: row.model.current ? "\u{F040A}" : ""
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
                text: row.model.title
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.body
                font.bold: row.model.current
              }
              Text {
                width: parent.width
                elide: Text.ElideRight
                textFormat: Text.PlainText
                text: row.model.artists
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
