#version 140
// SPDX-License-Identifier: GPL-3.0-or-later
// Kristall glass: shared vertex shader. "texcoord" carries the pixel position the fragment
// shader works in (top-left origin), not a normalised texture coordinate.
uniform mat4 modelViewProjectionMatrix;

in vec2 position;
in vec2 texcoord;

out vec2 vPos;

void main(void)
{
    gl_Position = modelViewProjectionMatrix * vec4(position, 0.0, 1.0);
    vPos = texcoord;
}
