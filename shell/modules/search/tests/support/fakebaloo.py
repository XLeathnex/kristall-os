#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Stand-in for baloosearch6 in the dev container (which has the Baloo libraries but not the
# indexer, baloo_file): answers `fakebaloo.py INDEX -l N words…` from a file list, one path per
# line, matching every word against file names the way Baloo's file-name terms do (word
# prefixes, case-insensitive). Used only to test Search's asynchronous plumbing and ranking.
import re
import sys

index = sys.argv[1]
args = sys.argv[2:]
limit = 20
words = []
i = 0
while i < len(args):
    if args[i] in ("-l", "--limit"):
        limit = int(args[i + 1])
        i += 2
        continue
    words += args[i].lower().split()
    i += 1
out = 0
with open(index) as f:
    for line in f:
        p = line.rstrip("\n")
        name = p.rsplit("/", 1)[-1].lower()
        terms = re.split(r"[^0-9a-zäöüß]+", name)
        if all(any(t.startswith(w) for t in terms) for w in words):
            print(p)
            out += 1
            if out >= limit:
                break
