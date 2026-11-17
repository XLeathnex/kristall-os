#!/usr/bin/python3
# win.py APPID [field] — prints the window's frame geometry "x y w h" (or one field / json)
import json, subprocess, sys
ws = json.loads(subprocess.run(["kristall-bridgectl", "windows"], capture_output=True, text=True).stdout)
for w in ws:
    if w["normal"] and sys.argv[1].lower() in (w["appId"] or "").lower():
        if len(sys.argv) > 2:
            print(json.dumps(w) if sys.argv[2] == "json" else w[sys.argv[2]])
        else:
            print(int(w["x"]), int(w["y"]), int(w["w"]), int(w["h"]))
        break
