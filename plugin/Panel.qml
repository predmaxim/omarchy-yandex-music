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
  readonly property var wave: Model.waveView(root.music)  // the My Wave screen: "playing" / "idle", null elsewhere
  readonly property var controls: Model.controlRow(root.music)
  readonly property string page: root.wave || (root.loggedIn ? "list" : "")
  readonly property string mood: Model.shownMood(root.music, root.pendingMood)

  // The keyboard cursor (Model.cursorRows: tabs, mood, seek, controls, list); the mouse moves it too.
  property string row: ""
  property int col: 0             // the item in the row; on a list row 1 is its wave button
  property int cur: -1            // the list row under the cursor
  property bool cursorPending: false  // just opened: the cursor goes to play/pause with the first state line
  property string pendingMood: ""     // stepped to, sent Model.MOOD_DELAY after the last step
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

  function cursor() { return { row: root.row, col: root.col, cur: root.cur } }
  function setCursor(row, col, cur) { root.row = row; root.col = col || 0; root.cur = cur === undefined ? -1 : cur }
  function placeCursor(c) { root.setCursor(c.row, c.col, c.cur) }
  // The mouse joins the cursor only when it really moves (rules.md §9): items swapped or moved under
  // a resting pointer (another tab, the wave starting) do not steal the keyboard's row.
  function hoverCursor(item, p, row, col, cur) { if (moveGate.moved(item, p)) root.setCursor(row, col, cur) }

  function refreshRows() {
    var r = Model.rows(root.music, root.pendingIndex)
    var sig = JSON.stringify(r)
    if (sig !== root.shownSig) { root.shownSig = sig; Model.syncRows(rowsModel, r); root.shown = r }
  }
  // The playing row in view: centred on a fresh list (no playing row: the top), else scrolled just enough.
  function showPlaying(fresh) {
    var i = root.shown.findIndex(function(r) { return r.current })
    if (i >= 0) list.positionViewAtIndex(i, fresh ? ListView.Center : ListView.Contain)
    else if (fresh) list.positionViewAtBeginning()
  }
  onMusicChanged: {
    var sig = JSON.stringify(root.music.source) + (root.music.search ? root.music.search.text : "")
    var fresh = sig !== root.sourceSig   // another list, or the window just opened
    if (fresh) { root.sourceSig = sig; root.askedAt = -1 }
    var moved = root.music.index !== root.seenIndex
    if (root.pendingIndex >= 0 && moved) root.pendingIndex = -1   // ymd answered
    root.seenIndex = root.music.index
    // The next track follows into view, unless the keyboard is browsing the list.
    if (fresh || (moved && root.row !== "list")) Qt.callLater(root.showPlaying, fresh)
    if (root.pendingMood === Model.shownMood(root.music, "")) root.pendingMood = ""   // ymd has it
    root.pos = Model.position(root.music, 0)   // 0 while the new file has no length yet
    root.posStamp = Date.now()
    refreshRows()
    if (root.cursorPending && root.music.running) {
      root.cursorPending = false
      root.placeCursor(Model.initialCursor(root.music))
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
    root.cursorPending = false
    root.placeCursor(Model.moveCursor(root.music, root.cursor(), step, root.pendingMood))
    moveGate.reset()
    if (root.row !== "list") return
    if (root.cur >= root.shown.length - 1) root.requestMore()
    list.positionViewAtIndex(root.cur, ListView.Contain)
  }

  function side(dx, event) {
    var r = Model.sideCursor(root.music, root.cursor(), dx, !!(event.modifiers & Qt.ShiftModifier), root.pendingMood)
    if (!r) { event.accepted = false; return }
    if (r.seek) { root.seekTo(root.pos + r.seek); return }
    root.col = r.col
    if (r.tab) root.pickTab(r.tab)
    if (r.mood) root.pickMood(r.mood)
  }

  function enter(event) {
    if (root.row === "tabs") root.pickTab(Model.TABS[root.col])
    else if (root.row === "mood") root.pickMood(root.music.moods[root.col])
    else if (root.row === "controls") root.activate(root.controls[root.col])
    else if (root.row === "list" && root.col === 1) root.waveFrom(root.cur)
    else if (root.row === "list") root.playRow(root.cur)
    else event.accepted = false
  }

  function activate(name) { if (name && Model.controlEnabled(name, root.music)) link.send(Model.controlCmd(name)) }

  // A tab shows its list (the search results give way); the one already shown stays as it is.
  function pickTab(v) {
    if (field.text !== "") field.text = ""
    if (v === root.music.source.type) return
    root.flushMood()   // a mood just stepped to still restarts the playing wave
    if (v === "likes") root.send("playlist")
    else root.send("wave", { mood: Model.waveMood(root.music) })
  }

  // A mood shows as picked at once; ymd gets it once stepping stops (a playing wave restarts once).
  function pickMood(m) {
    if (!m || m === root.mood) return
    root.pendingMood = m
    moodDelay.restart()
  }

  // The stepped-to mood goes out now instead of being lost: the window closes, the screen changes, another tab.
  function flushMood() {
    var m = moodDelay.running ? Model.moodToSend(root.music, root.pendingMood) : null
    if (m) root.send("wave", { mood: m })
    moodDelay.stop()   // after send: the link stays up while the timer runs
    root.pendingMood = ""
  }

  function playRow(i) {
    if (i < 0 || i >= root.shown.length) return
    if (Model.searching(root.music)) { root.send("play-search", { index: i }); field.text = "" }
    else { root.send("play", { index: i }); root.pendingIndex = i; pendingClear.restart() }
    root.setCursor("", 0)
  }

  function waveFrom(i) {
    if (i < 0 || i >= root.shown.length) return
    root.send("wave-track", { id: root.shown[i].id })
    field.text = ""
    root.setCursor("", 0)
  }

  // The rows changed under the cursor (another tab, the wave started or stopped, the track went away).
  function fixCursor() { root.placeCursor(Model.screenCursor(root.music, root.cursor())); moveGate.reset() }

  onShownChanged: {
    if (root.row !== "list") return
    if (root.shown.length === 0) { root.fixCursor(); return }
    if (root.cur >= root.shown.length) root.cur = root.shown.length - 1
    Qt.callLater(function() { list.positionViewAtIndex(root.cur, ListView.Contain) })
  }
  onHasTrackChanged: root.fixCursor()
  onPageChanged: {
    root.fixCursor()
    if (!root.wave) root.flushMood()
  }
  onLoggedInChanged: Qt.callLater(root.focusInput)

  onOpenedChanged: {
    if (opened) {
      root.setCursor("", 0)
      cursorPending = true
      moveGate.reset()
      Qt.callLater(function() { if (list.contentHeight < root.listSpace) root.requestMore() })
      Qt.callLater(root.focusInput)
    } else root.flushMood()
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

  PointerMoveGate { id: moveGate; referenceItem: card }
  ListModel { id: rowsModel }
  Link { id: link; wanted: root.opened || moodDelay.running }   // a mood stepped to right before closing still goes out

  Timer { id: pendingClear; interval: 3000; onTriggered: root.pendingIndex = -1 }

  Timer {
    interval: 500
    repeat: true
    running: root.opened && root.hasTrack && root.music.playing
    onTriggered: root.pos = Model.position(root.music, Date.now() - root.posStamp)
  }

  Timer {
    id: moodDelay
    interval: Model.MOOD_DELAY
    onTriggered: {
      var m = Model.moodToSend(root.music, root.pendingMood)
      if (m) root.send("wave", { mood: m })
      else root.pendingMood = ""
    }
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
      // The top stays where the tall list tab has it: the tabs row does not move when the compact
      // My Wave screen comes or goes.
      readonly property real listHeight: tabsRow.implicitHeight + hero.implicitHeight + headSeek.implicitHeight
          + sep.implicitHeight + root.listSpace + column.spacing * 4 + card.contentTopInset + card.contentBottomInset
      anchors.horizontalCenter: parent.horizontalCenter
      y: Math.max(Style.space(20), Math.round((modal.height - listHeight) / 2))
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

        // Wave / Liked, the search at the right: the first cursor row on every tab.
        Words {
          id: tabsRow
          visible: root.loggedIn
          width: parent.width
          panel: root
          rowName: "tabs"
          options: [{ value: "wave", label: root.tr("Wave") }, { value: "likes", label: root.tr("Liked") }]
          value: root.music.source.type
          onPicked: function(v) { root.pickTab(v) }

          // Search: borderless, a quiet hint at the right; always holds the keyboard. Typing shows the results.
          TextField {
            id: field
            anchors.right: parent.right
            anchors.rightMargin: Style.space(10)
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - tabsRow.wordsWidth - Style.space(24)
            horizontalAlignment: TextInput.AlignRight
            leftPadding: 0; rightPadding: 0; topPadding: 0; bottomPadding: 0
            background: null
            placeholderText: root.tr("Search…")
            placeholderTextColor: Util.alpha(root.bar.foreground, 0.4)
            foreground: root.bar.foreground
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.body
            cursorDelegate: Item {}
            onTextEdited: { root.setCursor("", 0); root.cursorPending = false; searchDelay.restart() }
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
            Keys.onEscapePressed: {
              if (text === "") { root.close(); return }
              text = ""
              root.setCursor("", 0)
              root.cursorPending = true   // play/pause again, once ymd answers without the search
            }
            Keys.onPressed: function(event) {
              if (!(event.modifiers & Qt.ControlModifier) || !root.hasTrack) return
              if (event.key === Qt.Key_L) { root.send("like"); event.accepted = true }
              else if (event.key === Qt.Key_D) { root.send("dislike"); event.accepted = true }
            }
          }
        }

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
              ControlButton {
                required property string modelData
                anchors.verticalCenter: parent.verticalCenter
                panel: root
                name: modelData
              }
            }
          }
        }

        // The header's seek: a cursor row, ←/→ ±10 s (Shift: 30).
        CursorSurface {
          id: headSeek
          visible: !root.wave && root.loggedIn
          enabled: root.hasTrack
          width: parent.width
          implicitHeight: headSeekRow.implicitHeight + Style.space(4) * 2
          hasCursor: root.row === "seek"
          foreground: root.bar.foreground
          SeekRow {
            id: headSeekRow
            anchors.verticalCenter: parent.verticalCenter
            x: Style.space(4)
            width: parent.width - x * 2
            enabled: headSeek.enabled
          }
          HoverHandler {
            id: headSeekHover
            onPointChanged: if (hovered && root.hasTrack) root.hoverCursor(headSeek, headSeekHover.point.position, "seek", 0)
          }
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

        Wave {
          visible: !!root.wave
          width: parent.width
          panel: root
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
            id: entry
            required property var model
            required property int index
            width: list.width
            implicitHeight: Math.max(Style.space(50), texts.implicitHeight + Style.spacing.rowPaddingX * 2)
            foreground: root.bar.foreground
            hasCursor: root.row === "list" && root.cur === index && root.col === 0
            current: entry.model.current   // the playing row: the stock light fill under the marker

            MouseArea {
              id: rowArea
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onPositionChanged: function(mouse) {
                if (moveGate.moved(rowArea, mouse)) root.setCursor("list", 0, entry.index)
              }
              onClicked: root.playRow(entry.index)
            }

            Text {
              id: mark
              anchors.left: parent.left
              anchors.leftMargin: Style.space(12)
              anchors.verticalCenter: parent.verticalCenter
              width: Style.space(20)
              text: entry.model.current ? Model.ICONS.play : ""
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
                text: entry.model.title
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.body
                font.bold: entry.model.current
              }
              Text {
                width: parent.width
                elide: Text.ElideRight
                textFormat: Text.PlainText
                text: entry.model.artists
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
              hasCursor: root.row === "list" && root.cur === entry.index && root.col === 1
              foreground: root.row === "list" && root.cur === entry.index ? root.bar.foreground : Qt.darker(root.bar.foreground, 1.4)
              fontFamily: root.bar.fontFamily
              onClicked: root.waveFrom(entry.index)
              HoverHandler {
                id: waveHover
                onPointChanged: if (hovered) root.hoverCursor(waveButton, waveHover.point.position, "list", 1, entry.index)
              }
            }
          }
        }
      }
    }
  }
}
