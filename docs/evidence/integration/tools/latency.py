#!/usr/bin/python3
# latency.py RAW — sends `transcribe` to assistant.sock, starts the test speech 0.3 s later (mic.py
# feeds it from /tmp/mic.say), and reports: ack, first partial, final transcript, end of speech → final.
import json, os, socket, sys, time
raw = sys.argv[1]
dur = os.path.getsize(raw) / 32000.0
s = socket.socket(socket.AF_UNIX); s.connect(os.path.join(os.environ["XDG_RUNTIME_DIR"], "kristall", "assistant.sock"))
f = s.makefile("rwb", buffering=0)
def send(o): f.write((json.dumps(o) + "\n").encode())
send({"type": "hello", "client": "integ-latency", "role": "ui"})
t0 = time.monotonic()
send({"id": "t1", "type": "transcribe", "no_speech_timeout_seconds": 20})
said = None
out = {"speech_seconds": round(dur, 2)}
s.settimeout(0.05)
buf = b""
while time.monotonic() - t0 < 60:
    if said is None and time.monotonic() - t0 >= 0.3:
        open("/tmp/mic.say", "w").write(raw); said = time.monotonic()
    try:
        chunk = s.recv(65536)
    except socket.timeout:
        continue
    if not chunk: break
    buf += chunk
    while b"\n" in buf:
        line, buf = buf.split(b"\n", 1)
        e = json.loads(line)
        t = round(time.monotonic() - t0, 2)
        if e.get("type") == "ack" and e.get("id") == "t1": out["ack_s"] = t
        if e.get("type") == "transcription" and not e.get("final") and "first_partial_s" not in out: out["first_partial_s"] = t
        if e.get("type") == "transcription" and e.get("final"):
            out["final_s"] = t; out["text"] = e.get("text")
            out["final_after_speech_end_s"] = round(time.monotonic() - said - dur, 2) if said else None
        if e.get("type") == "transcription_finished":
            out["outcome"] = e.get("outcome"); print(json.dumps(out, ensure_ascii=False)); sys.exit(0)
print(json.dumps(out, ensure_ascii=False))
