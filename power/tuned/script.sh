#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# tuned [script] hook, copied into every kristall-* profile directory (tuned only runs scripts that
# live inside a profile directory). Arguments from tuned: start | stop [full_rollback] | verify.
# The profile name is the name of the directory this file was installed in.
profile=$(basename "$(dirname "$(readlink -f "$0")")")
exec /usr/bin/kristall-power tuned-hook "${1:-start}" "$profile"
