/*
    Derived from KWin's screenshot plugin (src/plugins/screenshot/screenshotlayer.cpp, KWin 6.8.3).
    SPDX-FileCopyrightText: 2025 Xaver Hugl <xaver.hugl@kde.org>
    SPDX-FileCopyrightText: 2026 Kristall OS contributors

    SPDX-License-Identifier: GPL-2.0-or-later
*/
#include "screenshotlayer.h"
#include "core/output.h"
#include "opengl/eglcontext.h"
#include "opengl/glframebuffer.h"

using namespace KWin;

namespace Kristall
{

OffscreenLayer::OffscreenLayer(LogicalOutput *output, GLFramebuffer *buffer)
    : OutputLayer(output->backendOutput(), OutputLayerType::Primary)
    , m_buffer(buffer)
{
}

FormatModifierMap OffscreenLayer::supportedDrmFormats() const
{
    return {};
}

std::optional<OutputLayerBeginFrameInfo> OffscreenLayer::beginFrame(OutputFrame *frame)
{
    if (!m_buffer->context()->makeCurrent()) {
        return std::nullopt;
    }
    return OutputLayerBeginFrameInfo{
        .renderTarget = RenderTarget(m_buffer),
        .repaint = Region::infinite(),
    };
}

bool OffscreenLayer::endFrame(const Region &renderedRegion, const Region &damagedRegion, OutputFrame *frame)
{
    return true;
}

void OffscreenLayer::releaseBuffers()
{
}

}
