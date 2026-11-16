#version 140
// SPDX-License-Identifier: GPL-3.0-or-later
// Kristall glass: the Liquid Glass material for one "body" (one shape, or up to MAX_SHAPES shapes
// merged with a smooth union). Everything is in global device pixels (y down).
//
//   1. signed distance d to the outline (continuous-curvature corners = p-norm superellipse
//      corners, capsules = circles) and the outward normal n of the outline
//   2. lens: flat interior, curved rim of width "bezel"; the background is sampled at
//      pos + n * depth * (1 - t)^2, t = inside distance / bezel. Content from just outside the
//      shape is pulled into the rim and compressed; the interior is not displaced.
//   3. restrained chromatic split in the rim (R and B sampled at slightly different depths)
//   4. vibrancy (saturation), tint layer, legibility band for the current text scheme
//   5. inner shadow, specular rim light from lightDir, softer counter-light, pointer glow
//   6. triangular dither, premultiplied output with anti-aliased coverage
#define MAX_SHAPES 8

uniform sampler2D sharpTex;   // background capture (device resolution)
uniform sampler2D blurTex;    // blurred background (lower resolution)
uniform vec2 captureOrigin;   // global device position of capture texel (0,0)
uniform vec4 sharpInfo;       // allocated size xy, used size zw (texels)
uniform vec4 blurInfo;        // allocated size xy, used size zw (texels)
uniform vec2 texScale;        // texels per device px: x = sharp, y = blurred

uniform int shapeCount;
uniform float mergeK;                // smooth-union radius in device px (0 = hard union)
uniform vec4 geom[MAX_SHAPES];       // centre xy, half size zw
uniform vec4 corner[MAX_SHAPES];     // corner extent R, exponent p, 1/p, unused
uniform vec4 lens[MAX_SHAPES];       // bezel, depth, pressed 0..1, opacity
uniform vec4 tint[MAX_SHAPES];       // rgb, amount
uniform vec4 material[MAX_SHAPES];   // blurMix, saturation, specular, innerShadow
uniform vec4 extra[MAX_SHAPES];      // pointer xy, pointer sigma (0 = off), scheme 0 dark..1 light
uniform vec4 extra2[MAX_SHAPES];     // legibility strength, chroma, unused, unused

uniform vec2 lightDir;      // unit vector pointing towards the light (screen space, y down)
uniform float devScale;     // device px per logical px
uniform float windowOpacity;
uniform int mode;           // 0 high, 1 efficient, 2 reduce transparency, 3 isolate refraction
uniform vec3 opaqueColor;

in vec2 vPos;
out vec4 fragColor;

const vec3 LUMA = vec3(0.2126, 0.7152, 0.0722);

float shapeSdf(int i, vec2 pos, out vec2 n)
{
    vec2 rel = pos - geom[i].xy;
    vec2 a = abs(rel);
    float R = corner[i].x;
    vec2 q = a - (geom[i].zw - vec2(R));
    float d;
    vec2 g;
    if (q.x > 0.0 && q.y > 0.0) {
        float p = corner[i].y;
        if (p < 2.01) {
            float L = length(q);
            d = L - R;
            g = q / max(L, 1e-4);
        } else {
            // p-norm corner (G2-continuous with the straight edges), first-order distance
            float m = max(q.x, q.y);
            vec2 qn = q / m;
            float sp = pow(qn.x, p) + pow(qn.y, p);
            float L = m * pow(sp, corner[i].z);
            vec2 gr = vec2(pow(qn.x, p - 1.0), pow(qn.y, p - 1.0)) / pow(sp, 1.0 - corner[i].z);
            float gl = max(length(gr), 1e-4);
            d = (L - R) / gl;
            g = gr / gl;
        }
    } else if (q.x > q.y) {
        d = q.x - R;
        g = vec2(1.0, 0.0);
    } else {
        d = q.y - R;
        g = vec2(0.0, 1.0);
    }
    n = g * vec2(rel.x < 0.0 ? -1.0 : 1.0, rel.y < 0.0 ? -1.0 : 1.0);
    return d;
}

vec3 sampleTex(sampler2D tex, vec4 info, float scale, vec2 pos)
{
    vec2 t = (pos - captureOrigin) * scale;
    t = clamp(t, vec2(0.5), info.zw - vec2(0.5));
    return texture(tex, vec2(t.x, info.y - t.y) / info.xy).rgb;
}

vec3 sampleScene(vec2 pos, float blurMix)
{
    vec3 b = sampleTex(blurTex, blurInfo, texScale.y, pos);
    if (mode == 1 || blurMix >= 0.999) {
        return b;
    }
    vec3 s = sampleTex(sharpTex, sharpInfo, texScale.x, pos);
    return mix(s, b, blurMix);
}

float hash12(vec2 p)
{
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

void main(void)
{
    // --- 1. distance field of the body --------------------------------------------------
    vec2 n;
    float d = shapeSdf(0, vPos, n);
    vec4 pLens = lens[0];
    vec4 pTint = tint[0];
    vec4 pMat = material[0];
    vec4 pExtra = extra[0];
    vec4 pExtra2 = extra2[0];
    for (int i = 1; i < MAX_SHAPES; ++i) {
        if (i >= shapeCount) {
            break;
        }
        vec2 ni;
        float di = shapeSdf(i, vPos, ni);
        float h;
        if (mergeK > 0.0) {
            // polynomial smooth minimum; h = weight of the accumulated body
            h = clamp(0.5 + 0.5 * (di - d) / mergeK, 0.0, 1.0);
            d = mix(di, d, h) - mergeK * h * (1.0 - h);
            vec2 nn = mix(ni, n, h);
            n = dot(nn, nn) > 1e-8 ? normalize(nn) : n;
        } else {
            h = di < d ? 0.0 : 1.0;
            d = min(d, di);
            n = h > 0.5 ? n : ni;
        }
        pLens = mix(lens[i], pLens, h);
        pTint = mix(tint[i], pTint, h);
        pMat = mix(material[i], pMat, h);
        pExtra = mix(extra[i], pExtra, h);
        pExtra2 = mix(extra2[i], pExtra2, h);
    }
    if (d > 1.0) {
        discard;
    }
    float coverage = clamp(0.5 - d, 0.0, 1.0) * pLens.w * windowOpacity;
    float inside = max(-d, 0.0);
    float bezel = pLens.x;
    float t = bezel > 0.0 ? clamp(inside / bezel, 0.0, 1.0) : 1.0;
    float rim = 1.0 - t;
    float facing = dot(n, lightDir);

    // --- reduce transparency: opaque material, keep a faint rim so the shape reads -------
    if (mode == 2) {
        vec3 c = mix(opaqueColor, pTint.rgb, pTint.a * 0.3);
        float rimLine = exp(-inside / (0.8 * devScale));
        c = 1.0 - (1.0 - c) * (1.0 - vec3(0.12 * rimLine * (0.4 + 0.6 * max(facing, 0.0))));
        fragColor = vec4(c * coverage, coverage);
        return;
    }

    // --- 2. lens refraction ---------------------------------------------------------------
    float depth = pLens.y * (1.0 + 0.35 * pLens.z);
    float disp = depth * rim * rim;
    vec2 samplePos = vPos + n * disp;

    if (mode == 3) {
        // measurement aid: refraction only, no blur, tint, light or dither
        vec3 c = sampleTex(sharpTex, sharpInfo, texScale.x, samplePos);
        fragColor = vec4(c * coverage, coverage);
        return;
    }

    // --- 3. chromatic split, only where the surface is curved ------------------------------
    vec3 c;
    float chroma = pExtra2.y;
    if (mode == 0 && disp > 0.25 && chroma > 0.0) {
        c.g = sampleScene(samplePos, pMat.x).g;
        c.r = sampleScene(vPos + n * disp * (1.0 + chroma), pMat.x).r;
        c.b = sampleScene(vPos + n * disp * (1.0 - chroma), pMat.x).b;
    } else {
        c = sampleScene(samplePos, pMat.x);
    }

    // --- 4. vibrancy, tint, legibility --------------------------------------------------------
    float l0 = dot(c, LUMA);
    c = clamp(mix(vec3(l0), c, pMat.y), 0.0, 1.0);
    c = mix(c, pTint.rgb, pTint.a);
    float L = max(dot(c, LUMA), 1e-4);
    float legS = pExtra2.x;
    // light scheme (dark text): keep the glass in [0.52, 0.95]; dark scheme (light text): [0.05, 0.45]
    vec3 cLight = c;
    if (L < 0.52) {
        cLight = mix(c, vec3(1.0), legS * (0.52 - L) / (1.0 - L));
    } else if (L > 0.95) {
        cLight = c * mix(1.0, 0.95 / L, legS);
    }
    vec3 cDark = c;
    if (L > 0.45) {
        cDark = c * mix(1.0, 0.45 / L, legS);
    } else if (L < 0.05) {
        cDark = mix(c, vec3(1.0), legS * (0.05 - L) / (1.0 - L));
    }
    c = mix(cDark, cLight, pExtra.w);

    // --- 5. thickness: inner shadow, specular rim, counter light, pointer glow ------------
    if (mode == 1) {
        // efficient tier: one rim light term, no inner shadow or pointer glow
        float rimE = exp(-inside / (0.75 * devScale));
        float specE = pMat.z * rimE * (0.30 + 0.85 * abs(facing));
        c = 1.0 - (1.0 - c) * (1.0 - clamp(specE, 0.0, 1.0));
        c += (hash12(vPos) - 0.5) / 255.0;
        fragColor = vec4(clamp(c, 0.0, 1.0) * coverage, coverage);
        return;
    }
    float shadow = pMat.w * rim * rim * (0.55 + 0.45 * max(-facing, 0.0));
    c *= 1.0 - shadow;
    float rimLine = exp(-inside / (0.75 * devScale));
    float rimGlow = exp(-inside / max(bezel * 0.45, devScale));
    float key = pow(max(facing, 0.0), 1.5);
    float counter = pow(max(-facing, 0.0), 1.5) * 0.55;
    float spec = rimLine * (0.30 + 0.85 * (key + counter)) + rimGlow * 0.28 * (key + 0.5 * counter);
    spec *= pMat.z * (1.0 + 0.5 * pLens.z);
    if (pExtra.z > 0.0) {
        vec2 dp = vPos - pExtra.xy;
        float g = exp(-dot(dp, dp) / (2.0 * pExtra.z * pExtra.z));
        spec += g * (0.07 + 0.55 * rimLine * pMat.z);
    }
    c = mix(c, vec3(1.0), 0.07 * pLens.z);
    c = 1.0 - (1.0 - c) * (1.0 - clamp(spec, 0.0, 1.0));

    // --- 6. dither (triangular, +-1 LSB) and premultiplied output --------------------------
    c += (hash12(vPos) + hash12(vPos + 17.17) - 1.0) / 255.0;
    fragColor = vec4(clamp(c, 0.0, 1.0) * coverage, coverage);
}
