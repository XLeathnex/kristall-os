#version 140
// SPDX-License-Identifier: GPL-3.0-or-later
// Kristall glass: average luminance of the (blurred) background under one shape, written to
// one texel of a tiny strip that is read back asynchronously for the legibility decision.
uniform sampler2D src;
uniform vec2 srcCap;
uniform vec2 srcUsed;
uniform vec4 area;     // x0, y0, x1, y1 in source texels (top-left origin)

out vec4 fragColor;

void main(void)
{
    float sum = 0.0;
    float lo = 1.0;
    float hi = 0.0;
    for (int j = 0; j < 4; ++j) {
        for (int i = 0; i < 4; ++i) {
            vec2 p = mix(area.xy, area.zw, (vec2(float(i), float(j)) + 0.5) / 4.0);
            p = clamp(p, vec2(0.5), srcUsed - vec2(0.5));
            vec3 c = texture(src, vec2(p.x, srcCap.y - p.y) / srcCap).rgb;
            float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
            sum += l;
            lo = min(lo, l);
            hi = max(hi, l);
        }
    }
    fragColor = vec4(sum / 16.0, lo, hi, 1.0);
}
