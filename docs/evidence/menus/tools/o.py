#!/usr/bin/python3
# o.py — plays the owner through KWin's fake-input (the bridge tests' `owner` client).
#   o.py move X Y | click X Y [right] | dclick X Y | down X Y | up | key CHORD [hold_ms] | type TEXT | sleep MS | scroll X Y N
# CHORD: e.g. alt+space, meta+space, ctrl+q, return, esc, tab, shift+tab, left. Layout: German (QWERTZ)
# or US for `type` (env OWNER_LAYOUT=de|us, default de). Coordinates: logical (compositor) pixels.
import os, subprocess, sys, time

K = {"esc": 1, "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10, "0": 11, "minus": 12, "equal": 13,
     "backspace": 14, "tab": 15, "q": 16, "w": 17, "e": 18, "r": 19, "t": 20, "y": 21, "u": 22, "i": 23, "o": 24, "p": 25,
     "leftbrace": 26, "rightbrace": 27, "return": 28, "enter": 28, "ctrl": 29, "a": 30, "s": 31, "d": 32, "f": 33, "g": 34,
     "h": 35, "j": 36, "k": 37, "l": 38, "semicolon": 39, "apostrophe": 40, "grave": 41, "shift": 42, "backslash": 43,
     "z": 44, "x": 45, "c": 46, "v": 47, "b": 48, "n": 49, "m": 50, "comma": 51, "dot": 52, "slash": 53, "rightshift": 54,
     "alt": 56, "space": 57, "capslock": 58, "f1": 59, "f2": 60, "f3": 61, "f4": 62, "f5": 63, "f6": 64, "f7": 65, "f8": 66,
     "f9": 67, "f10": 68, "102nd": 86, "f11": 87, "f12": 88, "altgr": 100, "rightalt": 100, "home": 102, "up": 103, "pageup": 104,
     "left": 105, "right": 106, "end": 107, "down": 108, "pagedown": 109, "delete": 111, "meta": 125, "super": 125,
     "f23": 193, "lock": 0}
DE = {"y": "z", "z": "y"}
DE_CHARS = {"ä": ["apostrophe"], "ö": ["semicolon"], "ü": ["leftbrace"], "ß": ["minus"], "Ä": ["shift", "apostrophe"],
            "Ö": ["shift", "semicolon"], "Ü": ["shift", "leftbrace"], "-": ["slash"], ".": ["dot"], ",": ["comma"],
            "!": ["shift", "1"], "?": ["shift", "minus"], "@": ["altgr", "q"], ":": ["shift", "dot"], "'": ["shift", "backslash"],
            "/": ["shift", "7"], "(": ["shift", "8"], ")": ["shift", "9"], "+": ["rightbrace"], "_": ["shift", "slash"]}
US_CHARS = {"-": ["minus"], ".": ["dot"], ",": ["comma"], "!": ["shift", "1"], "?": ["shift", "slash"], "@": ["shift", "2"],
            ":": ["shift", "semicolon"], "'": ["apostrophe"], "/": ["slash"], "(": ["shift", "9"], ")": ["shift", "0"], "_": ["shift", "minus"]}
BTN = {"left": 272, "right": 273, "middle": 274}

lines = []
def cmd(s): lines.append(s)
def press(keys):
    for k in keys: cmd(f"key {K[k]} 1")
    for k in reversed(keys): cmd(f"key {K[k]} 0")
def chord(c):
    parts = c.lower().split("+")
    press([DE.get(p, p) if os.environ.get("OWNER_LAYOUT", "de") == "de" and len(parts) == 1 and False else p for p in parts])
def type_text(t):
    de = os.environ.get("OWNER_LAYOUT", "de") == "de"
    for ch in t:
        if ch == " ": press(["space"]); continue
        if ch == "\n": press(["return"]); continue
        table = DE_CHARS if de else US_CHARS
        if ch in table: press(table[ch]); continue
        low = ch.lower()
        if low.isdigit(): press(["shift", low] if False else [low]); continue
        key = DE.get(low, low) if de else low
        press(["shift", key] if ch.isupper() else [key])

args = sys.argv[1:]
i = 0
while i < len(args):
    a = args[i]
    if a == "move": cmd(f"move {args[i+1]} {args[i+2]}"); i += 3
    elif a in ("click", "dclick"):
        x, y = args[i+1], args[i+2]; i += 3
        b = BTN["left"]
        if i < len(args) and args[i] in BTN: b = BTN[args[i]]; i += 1
        cmd(f"move {x} {y}"); cmd("sync")
        for _ in range(2 if a == "dclick" else 1):
            cmd(f"button {b} 1"); cmd(f"button {b} 0")
    elif a == "down": cmd(f"move {args[i+1]} {args[i+2]}"); cmd(f"button 272 1"); i += 3
    elif a == "up": cmd("button 272 0"); i += 1
    elif a == "scroll": cmd(f"move {args[i+1]} {args[i+2]}"); cmd(f"axis 0 {args[i+3]}"); i += 4
    elif a == "key":
        c = args[i+1]; i += 2
        if i < len(args) and args[i].isdigit():
            parts = c.lower().split("+")
            for k in parts: cmd(f"key {K[k]} 1")
            cmd(f"sleep {args[i]}"); i += 1
            for k in reversed(parts): cmd(f"key {K[k]} 0")
        else:
            press(c.lower().split("+"))
    elif a == "type": type_text(args[i+1]); i += 2
    elif a == "sleep": cmd(f"sleep {args[i+1]}"); i += 2
    else: sys.exit(f"o.py: unknown {a}")

p = subprocess.Popen(["/opt/integ/owner"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
for l in lines:
    if l.startswith("sleep "):
        time.sleep(int(l.split()[1]) / 1000.0); continue
    p.stdin.write(l + "\n"); p.stdin.flush()
    p.stdout.readline()
    time.sleep(0.012)
p.stdin.close(); p.wait(5)
