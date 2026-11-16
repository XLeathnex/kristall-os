#version 140
// SPDX-License-Identifier: GPL-2.0-or-later
// Dual Kawase upsample, derived from KWin's blur effect (src/plugins/blur/shaders/upsample.frag,
// SPDX-FileCopyrightText: 2018 Alex Nemeth). Changed: texel units, clamped to the used area.
uniform sampler2D src;
uniform vec2 srcCap;
uniform vec2 srcUsed;
uniform float offset;

in vec2 vPos;

out vec4 fragColor;

vec4 tap(vec2 p)
{
    p = clamp(p, vec2(0.5), srcUsed - vec2(0.5));
    return texture(src, vec2(p.x, srcCap.y - p.y) / srcCap);
}

void main(void)
{
    vec2 p = vPos * 0.5;
    float a = offset;
    float b = 0.5 * offset;
    vec4 sum = tap(p + vec2(-a, 0.0));
    sum += tap(p + vec2(-b, b)) * 2.0;
    sum += tap(p + vec2(0.0, a));
    sum += tap(p + vec2(b, b)) * 2.0;
    sum += tap(p + vec2(a, 0.0));
    sum += tap(p + vec2(b, -b)) * 2.0;
    sum += tap(p + vec2(0.0, -a));
    sum += tap(p + vec2(-b, -b)) * 2.0;
    fragColor = sum / 12.0;
}
