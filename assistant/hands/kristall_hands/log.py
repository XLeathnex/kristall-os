# SPDX-License-Identifier: GPL-3.0-or-later
"""Logging to the journal (`journalctl --user -t kristall-hands`) or stderr.

Never log secrets: typed text and clipboard contents are logged by length only."""
from __future__ import annotations

import logging
import os
import sys

_log = logging.getLogger("kristall-hands")


def setup(verbose: bool = False) -> None:
    if _log.handlers:
        return
    level = logging.DEBUG if verbose or os.environ.get("KRISTALL_HANDS_DEBUG") else logging.INFO
    _log.setLevel(level)
    handler: logging.Handler
    if os.path.exists("/dev/log") and not os.environ.get("KRISTALL_HANDS_LOG_STDERR"):
        from logging.handlers import SysLogHandler
        try:
            handler = SysLogHandler(address="/dev/log", facility=SysLogHandler.LOG_USER)
            handler.ident = "kristall-hands: "
        except OSError:
            handler = logging.StreamHandler(sys.stderr)
    else:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("kristall-hands %(levelname)s %(message)s"))
    _log.addHandler(handler)
    # stdout is the MCP channel: nothing else may ever write there
    _log.propagate = False


debug = _log.debug
info = _log.info
warning = _log.warning
error = _log.error
exception = _log.exception
