#!/usr/bin/python3
# hands.py — plays the model: drives the installed /usr/bin/kristall-hands over MCP (stdio), each call
# decided first by the assistant daemon's real permission policy (assistant/core policy + the
# installed mcp.d drop-in), exactly as the daemon does. Usage: hands.py SCRIPT.json  (list of
# [tool, {args}] steps) or hands.py tools. Prints a log line per step.
import json, os, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, "/usr/lib/kristall/assistant")
from kristall_assistant.brain import mcp_config
from kristall_assistant.policy.policy import GrantStore, Policy, PolicyPaths

class Mcp:
    def __init__(self):
        self.p = subprocess.Popen(["/usr/bin/kristall-hands"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=open("/tmp/hands-integ.log", "a"))
        self.n = 0
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "integ", "version": "1"}})
    def rpc(self, method, params=None):
        self.n += 1
        self.p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}) + "\n").encode())
        self.p.stdin.flush()
        while True:
            m = json.loads(self.p.stdout.readline())
            if m.get("id") == self.n:
                return m
    def call(self, tool, args):
        r = self.rpc("tools/call", {"name": tool, "arguments": args}).get("result", {})
        txt = "\n".join(c.get("text", "") for c in r.get("content", []) if c.get("type") == "text")
        return txt, bool(r.get("isError"))

mcp = Mcp()
if sys.argv[1] == "tools":
    for t in mcp.rpc("tools/list")["result"]["tools"]:
        print(t["name"], "—", json.dumps(t.get("inputSchema", {}).get("properties", {}))[:300])
    sys.exit(0)
setup = mcp_config.load([Path("/usr/share/kristall/assistant/mcp.d")])
policy = Policy(PolicyPaths(Path(os.path.expanduser("~")), []), GrantStore(None), setup.decls)
for tool, args in json.load(open(sys.argv[1])):
    if tool == "sleep":
        time.sleep(args); continue
    d = policy.evaluate("mcp__hands__" + tool, args)
    pre = f"[policy {d.verdict}/{d.category}" + (f" asks: „{d.question['de']}“ → owner: allow once" if d.verdict == "ask" else "") + "]"
    if d.verdict == "deny":
        print(tool, json.dumps(args, ensure_ascii=False)[:120], pre, "→ not called", flush=True); continue
    t0 = time.monotonic()
    txt, err = mcp.call(tool, args)
    print(f"{tool} {json.dumps(args, ensure_ascii=False)[:140]} {pre} → {'ERROR ' if err else ''}{txt[:700]} ({(time.monotonic()-t0)*1000:.0f} ms)", flush=True)
