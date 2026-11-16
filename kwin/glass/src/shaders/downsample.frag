#version 140
// SPDX-License-Identifier: GPL-2.0-or-later
// Dual Kawase downsample, derived from KWin's blur effect (src/plugins/blur/shaders/downsample.frag,
// SPDX-FileCopyrightText: 2018 Alex Nemeth). Changed: works in texel units on partially used
// textures (taps are clamped to the used area, so reused larger textures never leak old content).
uniform sampler2D src;
uniform vec2 srcCap;   // allocated size of the source texture
uniform vec2 srcUsed;  // used area of the source texture, texels from the top-left corner
uniform float offset;

in vec2 vPos;          // destination pixel position, top-left origin

out vec4 fragColor;

vec4 tap(vec2 p)
{
    p = clamp(p, vec2(0.5), srcUsed - vec2(0.5));
    return texture(src, vec2(p.x, srcCap.y - p.y) / srcCap);
}

void main(void)
{
    vec2 p = vPos * 2.0;
    float o = 0.5 * offset;
    vec4 sum = tap(p) * 4.0;
    sum += tap(p + vec2(-o, -o));
    sum += tap(p + vec2(o, o));
    sum += tap(p + vec2(o, -o));
    sum += tap(p + vec2(-o, o));
    fragColor = sum / 8.0;
}
