import QtQuick

// A cover image. A new url shows once it has loaded: the previous picture stays until then,
// so a track change never blanks it.
Item {
  id: cover
  property string url: ""
  property string loadedUrl: ""
  readonly property bool ready: pic.status === Image.Ready
  onUrlChanged: if (!url) loadedUrl = ""

  Image {
    id: pic
    anchors.fill: parent
    source: cover.loadedUrl
    fillMode: Image.PreserveAspectCrop
    asynchronous: true
  }
  Image {   // loads the new url out of sight; the pixmap cache hands it to pic at once
    visible: false
    source: cover.url
    asynchronous: true
    onStatusChanged: if (status === Image.Ready || status === Image.Error) cover.loadedUrl = cover.url
  }
}
