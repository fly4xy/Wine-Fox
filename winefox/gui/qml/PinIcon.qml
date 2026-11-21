import QtQuick
import QtQuick.Shapes

// A pushpin: filled in the accent colour when pinned, an outline otherwise. A Shape, not a
// Canvas: every row of the apps list has one, and a Canvas repaints in software.
Item {
    id: pin
    property bool pinned: false
    property bool hovered: false
    readonly property color colour: pinned ? Theme.dim : hovered ? Theme.text : Theme.faint
    implicitWidth: 18
    implicitHeight: 18

    Shape {
        // drawn on a 16×16 grid, tilted like a pin pressed in
        width: 16
        height: 16
        anchors.centerIn: parent
        rotation: 45
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: pin.colour
            strokeWidth: 1.5
            fillColor: pin.pinned ? pin.colour : "transparent"
            joinStyle: ShapePath.RoundJoin
            capStyle: ShapePath.RoundCap
            PathSvg { path: "M 4.5 1.3 L 11.5 1.3 L 10.2 3.2 L 10.2 7 L 12.8 9.6 L 3.2 9.6 L 5.8 7 L 5.8 3.2 Z" }
        }
        ShapePath {
            strokeColor: pin.colour
            strokeWidth: 1.5
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathSvg { path: "M 8 9.6 L 8 15" }
        }
    }
}
