import QtQuick

// The mouse wheel for a Flickable (ListView, ScrollView), at the speed of Settings (or the
// desktop's lines per notch): Qt Quick's own step is slow. At an end the wheel goes on to the
// view around this one (a list inside a scrolling page).
WheelHandler {
    id: handler
    property Flickable flickable: null
    target: null
    acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad

    onWheel: (event) => {
        const f = handler.flickable
        if (!f) {
            event.accepted = false
            return
        }
        // by the wheel's turn (120 a notch, a share of it for high-resolution wheels and touchpads):
        // the device type is no guide, Wayland reports mice as touchpads; pixels only without a turn
        const delta = event.angleDelta.y !== 0 ? event.angleDelta.y / 120 * backend.scrollStep
                    : event.pixelDelta.y * backend.scrollStep / 40
        const top = f.originY - f.topMargin
        const bottom = Math.max(top, f.originY + f.contentHeight + f.bottomMargin - f.height)
        const y = Math.max(top, Math.min(bottom, f.contentY - delta))
        if (y === f.contentY) {
            event.accepted = false                 // at its end: the view around it scrolls
            return
        }
        f.contentY = y
        event.accepted = true
    }
}
