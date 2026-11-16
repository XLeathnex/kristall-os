#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Runs inside a real terminal emulator (foot) in the keyboard tests: puts the terminal in raw mode
# and appends every byte the terminal sends to the program as one JSON line to the file in argv[1]
# ({"hex": "03", "text": "\u0003"}), so a test can see exactly what Control-C or a paste delivered.
import json
import os
import sys
import termios
import tty

out = sys.argv[1]
fd = sys.stdin.fileno()
old = termios.tcgetattr(fd)
tty.setraw(fd)
try:
    with open(out, "a", buffering=1) as f:
        f.write(json.dumps({"ready": True}) + "\n")
        while True:
            data = os.read(fd, 4096)
            if not data:
                break
            f.write(json.dumps({"hex": data.hex(), "text": data.decode("utf-8", "replace")}) + "\n")
finally:
    termios.tcsetattr(fd, termios.TCSADRAIN, old)
