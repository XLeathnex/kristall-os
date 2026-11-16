// SPDX-License-Identifier: GPL-3.0-or-later
// A GlassSurface whose shape changes are always sent with sync "commit" (glass contract §4):
// the effect holds them until the surface commits the frame that draws the matching content.
// The core's GlassSurface sends changes of a GlassShape's geometry "immediate" (applied at the
// next compositor frame, possibly one frame before our content), which is fine for menus and
// panels but makes the Dock's capsule lead its icons by a frame while magnifying. Candidate for
// the core: a `frameSynced` property on GlassSurface.
import QtQuick
import qs.core

GlassSurface {
    function requestUpdate() {
        Qt.callLater(update, "commit");
    }
}
