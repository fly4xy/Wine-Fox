pragma Singleton
import QtQuick

// All colours and sizes of the interface. The colours are set from the chosen theme
// (winefox/themes.py) when the window opens and when the theme changes.
QtObject {
    property color bg: "#141415"
    property color sidebar: "#0f0f10"
    property color panel: "#19191b"
    property color raised: "#232325"
    property color hover: "#2d2d2f"
    property color border: "#323233"
    property color text: "#ededed"
    property color dim: "#a1a1a6"
    property color faint: "#85858b"
    property color accent: "#f0803c"
    property color accentHover: "#f28f53"
    property color accentText: "#141415"
    property color danger: "#e5484d"
    property color ok: "#4cc38a"

    property int titleBar: 0          // the height of Wine Fox's own title bar (WindowFrame), 0 with the system frame
    property var frame: null          // the main window's WindowFrame, for the buttons in its rows (WindowButtons)

    readonly property int radius: 8
    readonly property int gap: 12
    readonly property int pad: 20
    readonly property int rowHeight: 48
    readonly property int controlHeight: 34
    readonly property int fontSize: 13
    readonly property int smallFont: 11
    readonly property int titleFont: 20
    readonly property string mono: "monospace"
}
