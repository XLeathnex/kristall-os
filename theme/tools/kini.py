#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Merge KDE-style INI fragments into a config file without losing anything else in it.

    kini.py merge TARGET FRAGMENT...   set every key of the fragments in TARGET (other keys,
                                       groups, comments and order are kept; atomic replace)
    kini.py get FILE GROUP KEY         print one value (GROUP may be nested: "A][B")
    kini.py check FILE...              parse check (exit 1 on a malformed line)

KDE INI specifics handled: nested groups "[A][B]", keys with locale suffix "Name[de]", flags
"key[$e]", values containing '='. Standard library only (runs in the image build and on the
owner's machine).
"""
import os
import re
import sys
import tempfile

GROUP_RE = re.compile(r"^\[(.*)\]\s*$")


class KIni:
    def __init__(self, text=""):
        # list of (group, [lines]); group None = lines before the first group
        self.groups = [[None, []]]
        for raw in text.splitlines():
            m = GROUP_RE.match(raw.strip()) if raw.strip().startswith("[") else None
            if m:
                self.groups.append([m.group(1), []])
            else:
                self.groups[-1][1].append(raw)

    @staticmethod
    def parse_key(line):
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            return None
        return s.split("=", 1)[0].strip()

    def find_group(self, name):
        for g in self.groups:
            if g[0] == name:
                return g
        return None

    def items(self):
        for name, lines in self.groups:
            for line in lines:
                k = self.parse_key(line)
                if k is not None:
                    yield name, k, line.split("=", 1)[1].strip()

    def get(self, group, key):
        g = self.find_group(group)
        if not g:
            return None
        for line in g[1]:
            if self.parse_key(line) == key:
                return line.split("=", 1)[1].strip()
        return None

    def set(self, group, key, value):
        g = self.find_group(group)
        if g is None:
            if self.groups[-1][1] and self.groups[-1][1][-1].strip():
                self.groups[-1][1].append("")
            g = [group, []]
            self.groups.append(g)
        for i, line in enumerate(g[1]):
            if self.parse_key(line) == key:
                g[1][i] = f"{key}={value}"
                return
        # insert after the last key line of the group (keep trailing blank lines at the end)
        idx = len(g[1])
        while idx > 0 and not g[1][idx - 1].strip():
            idx -= 1
        g[1].insert(idx, f"{key}={value}")

    def text(self):
        out = []
        for name, lines in self.groups:
            if name is not None:
                out.append(f"[{name}]")
            out.extend(lines)
        s = "\n".join(out).strip("\n") + "\n"
        return re.sub(r"\n{3,}", "\n\n", s)


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def merge(target, fragments):
    ini = KIni(read(target))
    for frag in fragments:
        for group, key, value in KIni(read(frag)).items():
            if group is None:
                continue
            ini.set(group, key, value)
    d = os.path.dirname(os.path.abspath(target))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".kini-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(ini.text())
    os.chmod(tmp, 0o644)
    os.replace(tmp, target)


def check(paths):
    ok = True
    for p in paths:
        for n, line in enumerate(read(p).splitlines(), 1):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("["):
                if not GROUP_RE.match(s):
                    print(f"{p}:{n}: malformed group: {s}")
                    ok = False
            elif "=" not in s:
                print(f"{p}:{n}: not a key=value line: {s}")
                ok = False
    return ok


def main(argv):
    if len(argv) >= 3 and argv[1] == "merge":
        merge(argv[2], argv[3:])
        return 0
    if len(argv) == 5 and argv[1] == "get":
        v = KIni(read(argv[2])).get(argv[3], argv[4])
        if v is None:
            return 1
        print(v)
        return 0
    if len(argv) >= 3 and argv[1] == "check":
        return 0 if check(argv[2:]) else 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
