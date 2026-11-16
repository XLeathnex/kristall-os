// SPDX-License-Identifier: GPL-3.0-or-later
// Kristall assistant — the "crystal light" around the edge of the display.
//
// The light is drawn by four thin surfaces along the edges; this shader runs on each, in output
// coordinates, so the pieces join seamlessly. The light follows the display's rounded outline.
// Per pixel: inward distance from the outline (d), position along it (u), then
//   * a bright rim, rimWidth px wide, that hugs the rounded corners (almost white on dark),
//   * a coloured band and a wide soft glow reaching `reach` px inward; the glow's alpha falls off
//     as (1 − d/reach)^2.4, which reaches zero with zero slope (no visible band edge),
//   * our crystal palette — icy cyan → violet → magenta, cycling — flowing around the outline
//     (`phase` advances by one hue cycle every ~8 s at any point) with warm amber accents
//     travelling through it, and a prismatic phase offset between the rim and the glow,
//   * optional glints running around the edge (thinking),
//   * the entry sweep: the light starts at both bottom corners, runs up both sides and meets at
//     the top centre (sweep 0 → 1.2), with a brighter head at the front.
// Blending (premultiplied "over"): on dark content mostly additive (colour with little alpha: it
// glows and the content stays visible through it); on light content deeper, saturated colours
// with more alpha than colour, so the glow tints and slightly darkens white instead of washing out.
// Cost: one pass, ~90 ALU ops, no texture reads; only strip pixels run it.
#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 stripSize;     // logical px
    vec2 stripOrigin;   // strip origin in output coordinates (logical px)
    vec2 screenSize;    // output size (logical px)
    float radius;       // corner radius of the outline
    float time;         // seconds (frozen with Reduce Motion)
    float level;        // voice level, smoothed (spring; may overshoot 1 slightly)
    float intensity;    // 0..1 overall (setting × fade × mode)
    float rimWidth;     // bright rim, logical px
    float reach;        // glow reach at rest, logical px
    float phase;        // hue position in cycles (the integral of the flow speed: ~1 cycle per 8 s)
    float shimmer;      // 0..1 travelling glints
    float pulse;        // 0..1 extra brightness (error flash)
    float onLight;      // 0 dark appearance … 1 light appearance
    float sweep;        // entry front 0..1.2 (≥ 1.2: fully in)
    float bloom;        // brightness overshoot during the entry
    float accent;       // 0..1 strength of the amber accents
    float holeRadius;   // corner radius of the hole
    vec4 hole;          // x, y, w, h of the panel (output coordinates); w = 0: none
    vec4 colA;          // icy cyan
    vec4 colB;          // violet
    vec4 colC;          // magenta
    vec4 colD;          // amber accent
};

float sdRoundRect(vec2 p, vec2 b, float r) {
    vec2 q = abs(p) - b + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

// arc length along a rounded rectangle with half extents hb and corner radius R, clockwise from
// the end of the top-left corner; L = total length
float perimeter(vec2 q, vec2 hb, float R, out float L) {
    float sx = hb.x - R, sy = hb.y - R;
    float arc = 1.5707963 * R;
    float top = 2.0 * sx, side = 2.0 * sy;
    L = 2.0 * top + 2.0 * side + 4.0 * arc;
    vec2 a = abs(q);
    if (a.x > sx && a.y > sy) {
        vec2 v = q - vec2(sign(q.x) * sx, sign(q.y) * sy);
        float ang = atan(v.y, v.x);
        if (q.x > 0.0 && q.y < 0.0) return top + R * (ang + 1.5707963);
        if (q.x > 0.0) return top + arc + side + R * ang;
        if (q.y > 0.0) return 2.0 * top + 2.0 * arc + side + R * (ang - 1.5707963);
        return 2.0 * top + 3.0 * arc + 2.0 * side + R * (ang + 3.1415927);
    }
    if (hb.x - a.x < hb.y - a.y) {
        if (q.x > 0.0) return top + arc + (q.y + sy);
        return 2.0 * top + 3.0 * arc + side + (sy - q.y);
    }
    if (q.y < 0.0) return q.x + sx;
    return top + 2.0 * arc + side + (sx - q.x);
}

// the cyclic crystal gradient cyan → violet → magenta → cyan at phase ph (radians)
vec3 crystal(float ph) {
    vec3 w = max(vec3(0.0), cos(vec3(ph, ph - 2.0944, ph - 4.1888)));
    w = w * w;
    return (colA.rgb * w.x + colB.rgb * w.y + colC.rgb * w.z) / max(1e-3, w.x + w.y + w.z);
}

void main() {
    vec2 p = stripOrigin + qt_TexCoord0 * stripSize;
    vec2 hb = screenSize * 0.5;
    vec2 q = p - hb;
    float d = -sdRoundRect(q, hb, radius);          // depth inward from the outline
    float inside = clamp(d + 0.5, 0.0, 1.0);        // beyond the rounded corner: nothing
    d = max(d, 0.0);

    float R = max(radius, 48.0);
    float L;
    float u = perimeter(q, hb, R, L);
    float un = u / L;

    // ---- entry sweep: from the bottom corners up both sides, meeting at the top centre ----------
    float sx = hb.x - R, sy = hb.y - R, arc = 1.5707963 * R;
    float dt = abs(u - sx);
    dt = min(dt, L - dt);                           // distance from the top centre along the outline
    float dc = sx + arc + 2.0 * sy + 0.5 * arc;     // … of the bottom corners' midpoints
    float s = abs(dc - dt) / dc;                    // 0 at the bottom corners, 1 at the top centre
    float reveal = 1.0 - smoothstep(sweep - 0.12, sweep, s);
    float head = exp(-pow((s - sweep + 0.04) / 0.06, 2.0)) * (1.0 - smoothstep(0.95, 1.15, sweep));

    // ---- shape -------------------------------------------------------------------------------
    float lvl = clamp(level, 0.0, 1.15);
    float reachNow = reach * (0.88 + 0.2 * lvl + 0.08 * pulse + 0.08 * bloom);
    float x = clamp(d / reachNow, 0.0, 1.0);
    float glow = pow(1.0 - x, 1.8);                  // soft, zero slope at its end
    float band = exp(-d / (reachNow * 0.13));        // the luminous body next to the rim
    float rimW = rimWidth * (1.0 + 0.2 * lvl);
    float rim = 1.0 - smoothstep(rimW - 1.0, rimW + 0.75, d);
    float core = exp(-d / 1.1);                      // the hottest line right at the edge

    // ---- colour ------------------------------------------------------------------------------
    float ph = 6.2831853 * (2.0 * un - phase);
    ph += 0.5 * sin(6.2831853 * un * 3.0 + time * 0.7);   // a little turbulence in the flow
    vec3 bandCol = crystal(ph);
    vec3 glowCol = crystal(ph + 0.9);                    // prism: the glow runs ahead in hue
    // amber accents travelling through the palette (two, opposite each other, slower than the hue)
    float a1 = fract(un - time * 0.045);
    float a2 = fract(un - time * 0.045 + 0.5);
    float da = min(min(a1, 1.0 - a1), min(a2, 1.0 - a2));
    float amber = accent * exp(-pow(da / 0.055, 2.0));
    bandCol = mix(bandCol, colD.rgb, amber * 0.85);
    glowCol = mix(glowCol, colD.rgb, amber * mix(0.7, 0.3, onLight));   // deep amber over violet would turn brown

    // glints running around the edge (thinking)
    float gl = 0.0;
    if (shimmer > 0.001) {
        float s1 = fract(un * 3.0 - time * 0.55);
        float s2 = fract(un * 2.0 + time * 0.37 + 0.37);
        gl = (pow(1.0 - abs(s1 * 2.0 - 1.0), 40.0) + 0.7 * pow(1.0 - abs(s2 * 2.0 - 1.0), 40.0)) * shimmer;
    }

    float bright = (0.88 + 0.3 * lvl + 0.35 * pulse) * (1.0 + bloom) * (1.0 + 0.6 * head);
    float rimA = max(rim, core);
    float bandA = band * (0.8 + 0.2 * lvl) + gl * band;
    float glowA = glow * (0.62 + 0.3 * lvl) + gl * glow * 0.5;

    // Two parts, both premultiplied:
    //  * a colour layer composited "over" the content (glow, body, rim) — it makes the colour read
    //    over bright content (white pages, light photos). Light appearance: deep, saturated colours
    //    with most of the coverage, so white turns into the colour and is slightly darkened.
    //  * light added to the content (colour without alpha) — the luminous glow over dark content,
    //    the content stays visible through it. Dark appearance only.
    float kg = mix(0.3, 1.0, onLight), kb = mix(0.6, 0.92, onLight), kr = mix(0.78, 1.0, onLight);
    float bl = min(bright, 1.3);
    float cg = clamp(glowA * kg * bl, 0.0, 1.0);
    float cb = clamp(bandA * kb * bl, 0.0, 1.0);
    float cr = clamp(rimA * kr, 0.0, 1.0);
    vec3 rimTint = mix(mix(vec3(1.0), bandCol, 0.55), bandCol * 0.92, onLight);
    vec3 col = glowCol * cg;
    float a = cg;
    col = bandCol * cb + col * (1.0 - cb);
    a = cb + a * (1.0 - cb);
    col = rimTint * cr + col * (1.0 - cr);
    a = cr + a * (1.0 - cr);
    vec3 add = (mix(vec3(1.0), bandCol, 0.4) * rimA * 0.45 + bandCol * bandA * 0.5 + glowCol * glowA * 0.95) * bright;
    col += add * (1.0 - onLight);

    float k = intensity * inside * reveal;
    // the panel sits above the light: the light fades out under it
    if (hole.z > 0.0) {
        float dh = sdRoundRect(p - hole.xy - hole.zw * 0.5, hole.zw * 0.5, holeRadius);
        k *= smoothstep(-1.0, 12.0, dh);
    }
    a = clamp(a * k, 0.0, 1.0);
    col = min(col * k, vec3(1.0));
    fragColor = vec4(col, a) * qt_Opacity;
}
