# SPDX-License-Identifier: GPL-3.0-or-later
"""Kristall OS power component: policy, levers, automatic mode, status and diagnostics.

Python 3 standard library only, except `session` (python3-dbus + GLib via python3-gobject,
both already in the base image as dependencies of tuned/tuned-ppd)."""

VERSION = "1"
SCHEMA = 1
