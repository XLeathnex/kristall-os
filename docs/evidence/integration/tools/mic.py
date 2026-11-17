#!/usr/bin/python3
# mic.py FIFO — feeds a PipeWire pipe-source in real time: silence, or the raw file named in /tmp/mic.say
import os, sys, time
fifo = sys.argv[1]
f = open(fifo, "wb", buffering=0)
chunk = 640   # 20 ms of 16 kHz s16le mono
silence = b"\0" * chunk
data, pos = b"", 0
t = time.monotonic()
while True:
    if not data and os.path.exists("/tmp/mic.say"):
        path = open("/tmp/mic.say").read().strip()
        os.unlink("/tmp/mic.say")
        data, pos = open(path, "rb").read(), 0
    if data:
        part = data[pos:pos + chunk]; pos += chunk
        if pos >= len(data): data = b""
        f.write(part.ljust(chunk, b"\0"))
    else:
        f.write(silence)
    t += 0.02
    time.sleep(max(0, t - time.monotonic()))
