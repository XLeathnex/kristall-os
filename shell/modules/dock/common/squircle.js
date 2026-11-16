// SPDX-License-Identifier: GPL-3.0-or-later
// The rounded-square app icon outline (continuous curvature: a superellipse of exponent 5, close
// to the 22.37 % icon radius of design.md §5) as SVG data URLs for plates and placeholders.
.pragma library

let _path = "";

function path() {
    if (_path !== "")
        return _path;
    const n = 5, steps = 96, pts = [];
    for (let i = 0; i < steps; ++i) {
        const t = i / steps * 2 * Math.PI;
        const c = Math.cos(t), s = Math.sin(t);
        const x = 50 + 50 * Math.sign(c) * Math.pow(Math.abs(c), 2 / n);
        const y = 50 + 50 * Math.sign(s) * Math.pow(Math.abs(s), 2 / n);
        pts.push(x.toFixed(2) + " " + y.toFixed(2));
    }
    _path = "M" + pts.join(" L") + " Z";
    return _path;
}

// plate: light or dark material with a soft top light and a hairline rim
function plate(dark) {
    const top = dark ? "#48484C" : "#FFFFFF";
    const bottom = dark ? "#2C2C2F" : "#E6E6EB";
    const rim = dark ? "rgba(255,255,255,0.14)" : "rgba(0,0,0,0.10)";
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-2 -2 104 104">'
        + '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
        + '<stop offset="0" stop-color="' + top + '"/><stop offset="1" stop-color="' + bottom + '"/></linearGradient></defs>'
        + '<path d="' + path() + '" transform="translate(0 1.4)" fill="#000" fill-opacity="' + (dark ? 0.35 : 0.14) + '"/>'
        + '<path d="' + path() + '" fill="url(#g)" stroke="' + rim + '" stroke-width="0.8"/></svg>';
    return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
}

// a filled outline in one colour (folder tiles, placeholders, drop targets)
function fill(color, opacity) {
    const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-2 -2 104 104"><path d="' + path()
        + '" fill="' + color + '" fill-opacity="' + (opacity === undefined ? 1 : opacity) + '"/></svg>';
    return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
}
