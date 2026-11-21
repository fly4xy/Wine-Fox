pragma Singleton
import QtQuick

// All colours and sizes of the interface. The colours are set from the chosen theme
// (winefox/themes.py) when the window opens and when the theme changes.
QtObject {
    property color bg: "#0f1115"
    property color sidebar: "#0b0d10"
    property color panel: "#15181e"
    property color raised: "#1b1f27"
    property color hover: "#222733"
    property color border: "#262b36"
    property color text: "#e7e9ee"
    property color dim: "#8d95a3"
    property color faint: "#5a6170"
    property color accent: "#ff7a3d"
    property color accentHover: "#ff925f"
    property color accentText: "#16110e"
    property color danger: "#ef5b5b"
    property color ok: "#4cc38a"

    property int titleBar: 0          // the height of Wine Fox's own title bar (WindowFrame), 0 with the system frame

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
