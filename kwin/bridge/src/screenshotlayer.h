/*
    Derived from KWin's screenshot plugin (src/plugins/screenshot/screenshotlayer.h, KWin 6.8.3).
    SPDX-FileCopyrightText: 2025 Xaver Hugl <xaver.hugl@kde.org>
    SPDX-FileCopyrightText: 2026 Kristall OS contributors

    SPDX-License-Identifier: GPL-2.0-or-later
*/
#pragma once
#include "core/outputlayer.h"

namespace KWin
{
class GLFramebuffer;
class LogicalOutput;
}

namespace Kristall
{

// An output layer that renders into an offscreen framebuffer (never presented).
class OffscreenLayer : public KWin::OutputLayer
{
public:
    explicit OffscreenLayer(KWin::LogicalOutput *output, KWin::GLFramebuffer *buffer);

    KWin::FormatModifierMap supportedDrmFormats() const override;
    void releaseBuffers() override;

    std::optional<KWin::OutputLayerBeginFrameInfo> beginFrame(KWin::OutputFrame *frame = nullptr) override;
    bool endFrame(const KWin::Region &renderedRegion, const KWin::Region &damagedRegion, KWin::OutputFrame *frame) override;

private:
    KWin::GLFramebuffer *const m_buffer;
};

}
