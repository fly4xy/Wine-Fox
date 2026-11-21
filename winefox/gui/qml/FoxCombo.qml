import QtQuick
import QtQuick.Controls.Basic

// model: list of strings, or list of objects with textRole/valueRole
ComboBox {
    id: control
    implicitHeight: Theme.controlHeight
    font.pixelSize: Theme.fontSize
    hoverEnabled: true

    // The chosen value is kept apart from the index: the models are lists rebuilt from the
    // backend (prefixes are refreshed with the processes), and a new model resets the index.
    property var chosen: undefined

    // select the entry whose value is v
    function select(v) {
        chosen = v
        show()
    }
    function show() {
        if (chosen === undefined)
            return
        var i = valueRole ? indexOfValue(chosen) : find(chosen)
        currentIndex = i >= 0 ? i : 0
    }
    function value() {
        return chosen !== undefined ? chosen : (valueRole ? currentValue : currentText)
    }
    onModelChanged: Qt.callLater(show)
    onCountChanged: Qt.callLater(show)
    // a Connections, so users of FoxCombo can still have their own onActivated
    Connections {
        target: control
        function onActivated() { control.chosen = control.valueRole ? control.currentValue : control.currentText }
    }

    contentItem: Text {
        leftPadding: 10
        rightPadding: 28
        text: control.displayText
        font: control.font
        color: Theme.text
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideMiddle
    }
    indicator: Text {
        x: control.width - width - 10
        y: (control.height - height) / 2
        text: "▾"
        color: Theme.dim
        font.pixelSize: Theme.fontSize
    }
    background: Rectangle {
        radius: Theme.radius
        color: control.hovered ? Theme.hover : Theme.raised
        border.width: 1
        border.color: control.activeFocus || control.popup.visible ? Theme.accent : Theme.border
    }
    delegate: ItemDelegate {
        required property var modelData
        required property int index
        width: control.width
        height: 32
        hoverEnabled: true
        contentItem: Text {
            text: control.textRole ? modelData[control.textRole] : modelData
            color: index === control.currentIndex ? Theme.accent : Theme.text
            font.pixelSize: Theme.fontSize
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideMiddle
        }
        background: Rectangle { color: parent.hovered ? Theme.hover : "transparent"; radius: 6 }
    }
    popup: Popup {
        y: control.height + 4
        width: control.width
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 320)
        padding: 4
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator {}
        }
        background: Rectangle { color: Theme.panel; radius: Theme.radius; border.color: Theme.border }
    }
}
