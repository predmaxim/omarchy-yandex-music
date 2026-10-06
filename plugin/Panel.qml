import QtQuick
import QtQuick.Effects
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
  readonly property var wave: Model.waveView(root.music)  // the My Wave screen: "playing" / "idle", null elsewhere
  readonly property var controls: root.wave ? Model.waveControls(root.music) : Model.HEAD

  property int cur: -1
  property bool btnFocus: false
  property int head: -1           // cursor on root.controls (header buttons, or the wave screen's)
  property int srcCur: -1         // cursor on the wave screen's source row (Model.SOURCE_ROW)
  property bool cursorPending: false  // just opened: the cursor goes to play/pause with the first state line
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
    root.pos = Model.position(root.music, 0)   // 0 while the new file has no length yet
    root.posStamp = Date.now()
    refreshRows()
    if (root.cursorPending && root.music.running) {
      root.cursorPending = false
      var c = Model.initialCursor(root.music)
      root.srcCur = -1; root.btnFocus = false; root.head = c.head; root.cur = c.cur
    }
  }
  onPendingIndexChanged: refreshRows()

  function requestMore() {
    if (!root.opened || root.wave || !Model.wantMore(root.music, root.shown.length, root.askedAt)) return
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
    if (root.wave) {   // two rows: the source row above, the buttons below
      if (step < 0) { root.head = -1; if (root.srcCur < 0) root.srcCur = 0 }
      else if (root.head < 0) { root.srcCur = -1; root.head = Math.floor(root.controls.length / 2) }
      return
    }
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
    if (root.srcCur >= 0) { root.srcCur = Math.max(0, Math.min(Model.SOURCE_ROW.length - 1, root.srcCur + dx)); return }
    if (root.head >= 0) { root.head = Math.max(0, Math.min(root.controls.length - 1, root.head + dx)); return }
    if (root.cur >= 0) { root.btnFocus = dx > 0; return }
    event.accepted = false
  }

  function enter(event) {
    var inList = root.cur >= 0 && root.cur < root.shown.length
    if (root.srcCur >= 0) root.pickSource(Model.SOURCE_ROW[root.srcCur])
    else if (root.head >= 0) root.activate(root.controls[root.head])
    else if (inList && root.btnFocus) root.waveFrom(root.cur)
    else if (inList) root.playRow(root.cur)
    else event.accepted = false
  }

  function activate(name) { if (name && Model.controlEnabled(name, root.music)) link.send(Model.controlCmd(name)) }

  function pickSource(v) {
    if (v === "mood") moodBox.open()
    else if (v === "likes") root.send("playlist")
    else root.send("wave", { mood: Model.waveMood(root.music) })
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
  onWaveChanged: {   // another screen or view: the cursor stays on the buttons, if it was there
    var n = Model.waveControls(root.music).length
    root.head = root.head >= 0 && n > 0 ? Math.floor(n / 2) : -1
    if (root.wave) root.cur = -1
    else root.srcCur = -1
  }
  onLoggedInChanged: Qt.callLater(root.focusInput)

  onOpenedChanged: {
    if (opened) {
      cur = -1; head = -1; srcCur = -1; btnFocus = false
      cursorPending = true
      moveGate.reset()
      Qt.callLater(function() { if (list.contentHeight < root.listSpace) root.requestMore() })
      Qt.callLater(root.focusInput)
    }
  }

  // A header / wave screen button by name (Model.control): enabled only when it has something to act on.
  component Control: Button {
    id: control
    property string name
    readonly property int at: root.controls.indexOf(name)
    readonly property var look: Model.control(name, root.music)
    iconText: look.icon
    iconSize: Style.font.subtitle * 1.5
    horizontalPadding: Style.space(5)
    verticalPadding: Style.space(2)
    width: Math.max(implicitWidth, implicitHeight)
    height: width
    tooltipText: root.tr(look.tip)
    hasCursor: root.head === at && at >= 0
    enabled: Model.controlEnabled(name, root.music)
    foreground: enabled ? root.bar.foreground : Qt.darker(root.bar.foreground, 1.4)
    fontFamily: root.bar.fontFamily
    onClicked: root.activate(name)
    onHovered: function(h) { if (h && control.at >= 0) { root.cur = -1; root.srcCur = -1; root.head = control.at } }
  }

  // elapsed · slider · total; dimmed while disabled (no audible track)
  component SeekRow: Row {
    id: seekRow
    spacing: Style.space(8)
    Text {
      id: elapsed
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(40)
      horizontalAlignment: Text.AlignRight
      text: Model.fmtTime(slider.dragging ? slider.liveValue : root.pos)
      color: Qt.darker(root.bar.foreground, 1.4)
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.caption
    }
    PanelSlider {
      id: slider
      anchors.verticalCenter: parent.verticalCenter
      width: seekRow.width - elapsed.width - total.width - seekRow.spacing * 2
      bar: root.bar
      fillColor: seekRow.enabled ? root.bar.foreground : Qt.darker(root.bar.foreground, 1.4)
      knobColor: fillColor
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

  // A cover image, with rounded corners when radius > 0. A new url shows once it has loaded:
  // the previous picture stays until then, so a track change never blanks it.
  component Cover: Item {
    id: coverItem
    property string url: ""
    property real radius: 0
    property string shown: ""
    readonly property bool ready: pic.status === Image.Ready
    onUrlChanged: if (!url) shown = ""
    layer.enabled: radius > 0
    layer.effect: MultiEffect { maskEnabled: true; maskSource: coverMask; maskThresholdMin: 0.5; maskSpreadAtMin: 1.0 }
    Image {
      id: pic
      anchors.fill: parent
      source: coverItem.shown
      fillMode: Image.PreserveAspectCrop
      asynchronous: true
    }
    Image {   // loads the new url out of sight; the pixmap cache hands it to pic at once
      visible: false
      source: coverItem.url
      asynchronous: true
      onStatusChanged: if (status === Image.Ready || status === Image.Error) coverItem.shown = coverItem.url
    }
    Item {
      id: coverMask
      anchors.fill: parent
      visible: false
      layer.enabled: true
      Rectangle { anchors.fill: parent; radius: coverItem.radius }
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

      // My Wave while it plays: the track's cover, blurred and darkened, behind the whole card
      // (the one picture-as-colour exception to rules.md §9).
      Loader {
        anchors.fill: parent
        anchors.topMargin: card.borderTop
        anchors.rightMargin: card.borderRight
        anchors.bottomMargin: card.borderBottom
        anchors.leftMargin: card.borderLeft
        active: root.wave === "playing" && !!(root.music.track && root.music.track.cover)
        sourceComponent: Item {
          Cover {
            id: blurSource
            anchors.fill: parent
            url: root.music.track ? root.music.track.cover : ""
            visible: false
          }
          MultiEffect {
            anchors.fill: parent
            source: blurSource
            visible: blurSource.ready
            autoPaddingEnabled: false
            blurEnabled: true
            blur: 1.0
            blurMax: 64
            maskEnabled: true
            maskSource: blurMask
            maskThresholdMin: 0.5
            maskSpreadAtMin: 1.0
          }
          Rectangle {   // darkened toward the theme's background, so the text stays readable
            anchors.fill: parent
            visible: blurSource.ready
            radius: blurMask.children[0].radius
            color: Color.menu.scrim
          }
          Item {
            id: blurMask
            anchors.fill: parent
            visible: false
            layer.enabled: true
            Rectangle { anchors.fill: parent; radius: Math.max(0, card.radius - card.borderLeft) }
          }
        }
      }

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
          id: hero
          visible: !root.wave
          title: root.music.track ? root.music.track.title : root.tr("Yandex Music")
          meta: !root.music.running ? root.tr("Music service is not running")
              : root.music.auth !== "ok" ? root.tr("Not logged in")
              : root.music.track ? Model.subtitle(root.music, root.tr) : root.tr("Nothing is playing")
          foreground: root.bar.foreground
          fontFamily: root.bar.fontFamily
          iconComponent: Item {
            implicitWidth: Style.space(56); implicitHeight: Style.space(56)
            Cover {
              id: headCover
              anchors.fill: parent
              url: root.music.track ? root.music.track.cover : ""
            }
            Text {
              anchors.centerIn: parent
              visible: !headCover.ready
              text: Model.view(root.music).icon
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.display
            }
          }
          trailingControl: Row {   // always there while logged in: disabled, not hidden, without a track
            visible: root.loggedIn
            spacing: Style.space(10)
            Repeater {
              model: Model.HEAD
              Control {
                required property string modelData
                anchors.verticalCenter: parent.verticalCenter
                name: modelData
              }
            }
          }
        }

        SeekRow {
          id: headSeek
          visible: !root.wave && root.loggedIn
          enabled: root.hasTrack
          width: parent.width
        }

        PanelSeparator { id: sep; visible: !root.wave; foreground: root.bar.foreground }

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
          onTextEdited: { root.cur = -1; root.head = -1; root.srcCur = -1; root.cursorPending = false; searchDelay.restart() }
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

        // Source: Wave / Liked + mood (only for My Wave); hidden while searching. Centered on the wave screen.
        Row {
          visible: root.loggedIn && !Model.searching(root.music)
          x: root.wave ? (parent.width - width) / 2 : 0
          spacing: Style.space(10)
          ButtonGroup {
            options: [{ value: "wave", label: root.tr("Wave") }, { value: "likes", label: root.tr("Liked") }]
            value: root.music.source.type === "wave" || root.music.source.type === "likes" ? root.music.source.type : ""
            focusable: false
            cursorIndex: root.srcCur < 2 ? root.srcCur : -1
            foreground: root.bar.foreground
            fontFamily: root.bar.fontFamily
            onChanged: function(v) { root.pickSource(v) }
          }
          Dropdown {
            id: moodBox
            visible: root.music.source.type === "wave"
            width: Style.spacing.dropdownWidth
            showLabel: false
            hasCursor: root.srcCur === 2
            options: Model.moodOptions(root.music, root.tr)
            value: root.music.source.mood || "all"
            foreground: root.bar.foreground
            fontFamily: root.bar.fontFamily
            onChanged: function(v) { if (v !== (root.music.source.mood || "all")) root.send("wave", { mood: v }) }
            onPopupOpenChanged: if (!popupOpen) Qt.callLater(root.focusInput)   // the field holds the keys again
          }
        }

        // My Wave: the cover and the player under it; before the wave starts, a placeholder and ▶.
        Item {
          id: waveBody
          visible: !!root.wave
          width: parent.width
          // as tall as the header and list it stands for: the window keeps its size across tabs
          height: Math.max(waveColumn.implicitHeight,
                           hero.implicitHeight + headSeek.implicitHeight + sep.implicitHeight + root.listSpace + column.spacing * 3)

          Column {
            id: waveColumn
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            spacing: Style.space(10)

            Item {
              anchors.horizontalCenter: parent.horizontalCenter
              width: Math.round(waveBody.width * 0.64)
              height: width
              Cover {
                id: bigCover
                anchors.fill: parent
                visible: root.wave === "playing"
                radius: Style.cornerRadius
                url: root.music.track ? (root.music.track.cover_big || root.music.track.cover) : ""
              }
              Text {
                anchors.centerIn: parent
                visible: root.wave === "playing" && !bigCover.ready
                text: Model.ICONS.myWave
                color: Qt.darker(root.bar.foreground, 1.4)
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.display * 3
              }
              Rectangle {
                anchors.fill: parent
                visible: root.wave === "idle"
                radius: Style.cornerRadius
                color: "transparent"
                border.width: 1
                border.color: Util.alpha(root.bar.foreground, 0.25)
                Column {
                  anchors.centerIn: parent
                  width: parent.width - Style.space(24)
                  spacing: Style.space(10)
                  Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: Model.ICONS.myWave
                    color: root.bar.foreground
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.display * 3
                  }
                  Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    textFormat: Text.PlainText
                    text: root.tr("My Wave")
                    color: root.bar.foreground
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.title
                    font.bold: true
                  }
                  Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    textFormat: Text.PlainText
                    text: root.music.error ? Model.subtitle(root.music, root.tr) : Model.moodLabel(root.music.source.mood, root.tr)
                    color: Qt.darker(root.bar.foreground, 1.4)
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.body
                  }
                }
              }
            }

            // Title, artists and seek: kept (unseen) before the wave starts, so ▶ sits where ⏯ will be.
            Item { width: 1; height: Style.space(4) }
            Text {
              width: parent.width
              opacity: root.wave === "playing" ? 1 : 0
              horizontalAlignment: Text.AlignHCenter
              elide: Text.ElideRight
              textFormat: Text.PlainText
              text: root.music.track ? root.music.track.title : " "
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.heading
              font.bold: true
            }
            Text {
              width: parent.width
              opacity: root.wave === "playing" ? 1 : 0
              horizontalAlignment: Text.AlignHCenter
              elide: Text.ElideRight
              textFormat: Text.PlainText
              text: root.music.error ? Model.subtitle(root.music, root.tr) : root.music.track ? root.music.track.artists : " "
              color: Qt.darker(root.bar.foreground, 1.4)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.body
            }
            SeekRow {
              width: parent.width
              opacity: root.wave === "playing" ? 1 : 0
              enabled: root.wave === "playing" && root.hasTrack
            }

            // dislike at the left edge, like at the right, prev · play/pause · next between them
            Item {
              width: parent.width
              height: bigToggle.height
              Control {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                visible: root.wave === "playing"
                name: "dislike"
                iconSize: Style.font.display
              }
              Row {
                anchors.centerIn: parent
                spacing: Style.space(26)
                Control { anchors.verticalCenter: parent.verticalCenter; visible: root.wave === "playing"; name: "prev"; iconSize: Style.font.display }
                Control { id: bigToggle; anchors.verticalCenter: parent.verticalCenter; name: root.wave === "idle" ? "start" : "toggle"; iconSize: Style.font.display * 1.75 }
                Control { anchors.verticalCenter: parent.verticalCenter; visible: root.wave === "playing"; name: "next"; iconSize: Style.font.display }
              }
              Control {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                visible: root.wave === "playing"
                name: "like"
                iconSize: Style.font.display
              }
            }
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
          visible: root.loggedIn && !root.wave && root.music.loading && root.shown.length === 0 && !Model.searching(root.music)
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
          visible: root.loggedIn && !root.wave && !skeleton.visible
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
              text: row.model.current ? Model.ICONS.play : ""
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
              iconText: Model.ICONS.wave
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
