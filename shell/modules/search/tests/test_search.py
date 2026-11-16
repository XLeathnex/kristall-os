#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Search ("Search or Ask") tests — run inside the dev container under dbus-run-session (run.sh).

Sections: static behaviour looks. The shortcut is pressed for real (Meta+Space through KWin's
in-process kglobalaccel, reading our desktop file from XDG_DATA_DIRS like /usr/share on the image)
and every query is typed with real key events. Files come from a stand-in for baloosearch6 over a
50 000-file tree (the container has Baloo's libraries but not its indexer)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SEARCH = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(os.path.dirname(SEARCH), "dock", "tests", "support"))
import appsession as A  # noqa: E402
from PIL import Image  # noqa: E402
sys.path.insert(0, os.path.join(A.REPO, "kwin", "glass", "tests", "support"))
import pattern  # noqa: E402

EVIDENCE = os.path.join(SEARCH, "tests", "evidence")
failures, results = [], {}
check, info = A.check_factory(failures, results)
wait_until = A.wait_until

GERMAN_APPS = ["Kalender", "Kalkulator", "Karten", "Kamera", "Notizen", "Erinnerungen", "Fotos", "Vorschau", "Wetter",
               "Aktien", "Bücher", "Podcasts", "Uhr", "Schachspiel", "Lexikon", "Tabellenkalkulation", "Textverarbeitung",
               "Präsentation", "Übersetzer", "Bildbearbeitung", "Videoschnitt", "Tonaufnahme", "Zeichenpalette", "Schriftsammlung"]


def save(img, name, crop=None):
    im = Image.fromarray(img)
    if crop:
        im = im.crop(crop)
    os.makedirs(EVIDENCE, exist_ok=True)
    if im.size[0] * im.size[1] > 600000:      # large shots as JPEG: evidence of all modules < 5 MB
        im.convert("RGB").save(os.path.join(EVIDENCE, name.replace(".png", ".jpg")), quality=84, optimize=True)
    else:
        im.save(os.path.join(EVIDENCE, name), optimize=True)


def sysconf_tree(tmp):
    """the image's system-wide files for this module: /usr/share/kglobalaccel/org.kristall.search.desktop"""
    root = os.path.join(tmp, "sysconf")
    os.makedirs(os.path.join(root, "usr", "share", "kglobalaccel"), exist_ok=True)
    shutil.copy(os.path.join(SEARCH, "kglobalaccel", "org.kristall.search.desktop"), os.path.join(root, "usr", "share", "kglobalaccel"))
    return root


def shell_copy_with_assistant(tmp):
    """a copy of the shell with a probe `assistant` module that claims its target and logs requests"""
    dst = os.path.join(tmp, "shell")
    shutil.copytree(A.SHELL, dst, ignore=shutil.ignore_patterns("tests", "evidence", "__pycache__"))
    d = os.path.join(dst, "modules", "assistant")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "Module.qml"), "w") as f:
        f.write("import QtQuick\nimport Quickshell\nimport qs.services\nScope {\n"
                " Component.onCompleted: ShellBus.claim('assistant')\n"
                " Connections { target: ShellBus; function onRequested(t, a, arg, o) { if (t === 'assistant') console.info('ASSISTANT-REQUEST', JSON.stringify([a, arg, o])); } }\n}\n")
    return dst


def make_files(home, n=50000):
    words = ["Rechnung", "Urlaub", "Bewerbung", "Notizen", "Projekt", "Steuer", "Foto", "Vertrag", "Präsentation", "Lebenslauf",
             "Budget", "Einkaufsliste", "Roblox", "Blender", "Szene", "Skript", "Musik", "Video", "Brief", "Protokoll"]
    exts = [".pdf", ".odt", ".png", ".jpg", ".txt", ".blend", ".md", ".mp4", ".ods", ".py"]
    dirs = ["Dokumente", "Bilder", "Downloads", "Musik", "Videos", "Projekte/roblox", "Projekte/blender", "Projekte/web/src"]
    paths = []
    for i in range(n):
        d = os.path.join(home, dirs[i % len(dirs)], f"ordner{(i // 500) % 40}")
        paths.append(os.path.join(d, f"{words[(i * 7) % len(words)]} {i // len(words)}{exts[i % len(exts)]}"))
    special = [os.path.join(home, "Dokumente", "Rechnung Fahrrad 2026.pdf"), os.path.join(home, "Dokumente", "Steuererklärung 2025.pdf"),
               os.path.join(home, "Dokumente", "Mietvertrag Wohnung.pdf")]
    paths = special + paths
    for p in paths[:400]:            # a real part of the tree exists on disk (open/reveal)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w").close()
    idx = os.path.join(home, ".file-index")
    with open(idx, "w") as f:
        f.write("\n".join(paths) + "\n")
    return idx, special


def state(s):
    return json.loads(s.ipc("searchtest", "state"))


def wait_state(s, pred, timeout=5.0):
    last = [None]

    def f():
        try:
            st = state(s)
        except Exception:
            return None
        last[0] = st
        return st if pred(st) else None
    return wait_until(f, timeout, 0.1) or last[0]


def items(st):
    return [r for r in st["rows"] if r["kind"] == "item"]


def type_query(s, text):
    """clear the field (Ctrl+A, ⌫) and type `text` with real key events"""
    s.tap("leftctrl", "a")
    s.tap("backspace")
    time.sleep(0.1)
    for ch in text:
        if ch == " ":
            s.tap("space")
        elif ch == ",":
            s.tap("comma")
        elif ch == "*":
            s.tap("leftshift", "8")        # US layout in the test session
        elif ch.lower() in A.KEY:
            s.tap(ch.lower())
    return wait_state(s, lambda st: st["query"] == text, 4)


def select(s, rid):
    """move the selection to row `rid` with real ↓/↑ presses"""
    st = state(s)
    ids = [i["id"] for i in items(st)]
    if rid not in ids or st["selected"] not in ids:
        raise RuntimeError(f"cannot select {rid}: {json.dumps(st, ensure_ascii=False)[:600]}")
    d = ids.index(rid) - ids.index(st["selected"])
    for _ in range(abs(d)):
        s.tap("down" if d > 0 else "up")
    return wait_state(s, lambda st: st["selected"] == rid, 2)


def open_with_shortcut(s):
    s.tap("leftmeta", "space")
    return wait_state(s, lambda st: st["open"], 6)


# ---------------------------------------------------------------------------------------------------
def test_static():
    print("== static", flush=True)
    t = json.load(open(os.path.join(SEARCH, "strings.json")))
    check("strings: German and English have the same keys", set(t["en"]) == set(t["de"]))
    d = open(os.path.join(SEARCH, "kglobalaccel", "org.kristall.search.desktop")).read()
    check("global shortcut: Meta+Space runs kristall-shellctl search toggle", "X-KDE-Shortcuts=Meta+Space" in d and "kristall-shellctl search toggle" in d)


def test_behaviour():
    print("== behaviour: shortcut, typing, ranking, every result type, Ask, latency", flush=True)
    tmp = tempfile.mkdtemp(prefix="kristall-search-")
    sysconf = sysconf_tree(tmp)
    shell = shell_copy_with_assistant(tmp)
    s = A.AppsSession(name="search", global_shortcuts=True, sysconf=sysconf, shell_path=shell)
    # a few hundred apps
    for i in range(300):
        s.desktop(f"org.example.app{i:03d}", f"Beispiel {['Studio', 'Werkzeug', 'Editor', 'Player', 'Manager'][i % 5]} {i}",
                  extra=f"Keywords=demo;test{i};\nGenericName=Generic Tool {i}\n")
    for i, n in enumerate(GERMAN_APPS):
        s.desktop(f"de.kristall.test.{i}", n, icon=["accessories-calculator", "kcalc", "okular", "gwenview", "kate"][i % 5])
    for kcm, name in (("kcm_networkmanagement", "Wi-Fi & Networking"), ("kcm_kscreen", "Display Configuration"), ("kcm_pulseaudio", "Sound")):
        s.desktop(kcm, name, icon="preferences-system", extra="NoDisplay=true\n")
    idx, special = make_files(s.home)
    s.start()
    env = {"KRISTALL_SEARCH_FILES_CMD": f"{sys.executable} {os.path.join(HERE, 'support', 'fakebaloo.py')} {idx}"}
    try:
        bg = os.path.join(s.tmp, "bg.png")
        Image.fromarray(pattern.busy(s.width, s.height)).save(bg)
        s.background(bg)
        s.start_shell(extra_env=env, path=shell)
        wait_until(lambda: "module search loaded" in s.shell_log(), 15)
        st = wait_state(s, lambda st: st["apps"] > 300, 20)
        check("catalogue: a few hundred apps", st["apps"] > 300, str(st["apps"]))
        # ---- the shortcut (real Meta+Space through KWin's kglobalaccel → kristall-shellctl)
        st = open_with_shortcut(s)
        check("Meta+Space opens Search (system-wide kglobalaccel file → kristall-shellctl)", bool(st and st["open"]))
        time.sleep(0.5)
        save(s.screenshot(), "search-empty-light-1.0x.png", crop=(240, 120, 1040, 300))
        # ---- ranking with German queries and typos
        cases = [("dateien", "app:org.kde.dolphin"), ("dolhpin", "app:org.kde.dolphin"), ("termnial", "app:org.kde.konsole"),
                 ("systemeinst", "app:systemsettings"), ("textedit", "app:org.kde.kate"), ("kalkulatr", "app:de.kristall.test.1"),
                 ("ubersetzer", "app:de.kristall.test.18"), ("tabellen", "app:de.kristall.test.15")]
        for q, want in cases:
            st = type_query(s, q)
            its = items(st)
            check(f"“{q}” → top hit {want}", bool(its) and its[0]["id"] == want, json.dumps([i["id"] for i in its[:4]]))
        # ---- keystroke → the frame that shows the new results (real key events, 50 000-file index)
        s.tap("leftctrl", "a")
        s.tap("backspace")
        time.sleep(0.6)
        sent = []
        word = "beispielstudiorechnungfahrrad"
        for ch in word:
            t = time.time() * 1000.0
            s.tap(ch)
            sent.append(t)
            time.sleep(0.15)                  # a brisk typist: ~7 keys a second
        time.sleep(0.6)
        log = json.loads(s.ipc("searchtest", "frameLog"))
        stq = state(s)
        if stq["query"] != word:
            info(f"after typing: query={stq['query']!r} ({len(log)} frames logged)")
        lat = []
        for k, ch in enumerate(word):
            q = word[:k + 1]
            f = next((x for x in log if x["q"] == q), None)
            if f:
                lat.append(f["frameAt"] - sent[k])
        lat.sort()
        p50 = lat[len(lat) // 2] if lat else None
        p95 = lat[min(len(lat) - 1, int(round(len(lat) * 0.95)) - 1)] if lat else None
        proc = sorted(x["frameAt"] - x["keyAt"] for x in log[-len(word):])
        results["search_key_to_frame_ms"] = {"n": len(lat), "p50": p50, "p95": p95, "max": lat[-1] if lat else None,
                                             "shell_text_to_frame_p50": proc[len(proc) // 2] if proc else None,
                                             "shell_text_to_frame_p95": proc[min(len(proc) - 1, int(round(len(proc) * 0.95)) - 1)] if proc else None,
                                             "renderer": "Qt Quick software (headless llvmpipe session)"}
        info("keystroke → frame (ms): " + json.dumps(results["search_key_to_frame_ms"]))
        check("every keystroke produced a frame with its results", len(lat) == len(word), f"{len(lat)}/{len(word)}")
        check("keystroke → frame p95 within one 120 Hz frame of work in the shell (text change → frame ≤ 8.3 ms)",
              bool(proc) and results["search_key_to_frame_ms"]["shell_text_to_frame_p95"] <= 8.3, json.dumps(results["search_key_to_frame_ms"]))
        for q, want in (("wlan", "set:kcm_networkmanagement"), ("maus", "set:kcm_mouse"), ("bildschirm", "set:kcm_kscreen"),
                        ("tastatur", "set:kcm_keyboard"), ("lautstarke", "set:kcm_pulseaudio")):
            st = type_query(s, q)
            ids = [i["id"] for i in items(st)]
            check(f"System Settings page by name: “{q}” → {want}", want in ids, json.dumps(ids[:6]))
        st = type_query(s, "sperren")
        check("action: “sperren” → Bildschirm sperren", "act:lock" in [i["id"] for i in items(st)])
        # ---- calculator and conversions
        for q, want in (("3,5*2", "= 7"), ("5 km in mi", "= 3,106855961 mi"), ("100 f in c", "= 37,77777778 °C")):
            st = type_query(s, q)
            its = items(st)
            check(f"calculation “{q}” {want}", bool(its) and its[0]["title"] == want, json.dumps([i["title"] for i in its[:2]], ensure_ascii=False))
        st = type_query(s, "5 km in mi")
        s.tap("return")
        st = wait_state(s, lambda st: not st["open"], 3)
        check("↩ on a calculation copies the result and closes", bool(st) and st["lastActivated"].startswith("calc:3,106855961"), st and st["lastActivated"])
        open_with_shortcut(s)
        # ---- learned preference: “kal” picks Kalender first by default; the owner opens Kalkulator twice
        st = type_query(s, "kal")
        first = items(st)[0]["id"]
        target = "app:de.kristall.test.1" if first != "app:de.kristall.test.1" else "app:de.kristall.test.0"
        for _ in range(2):
            st = type_query(s, "kal")
            ids = [i["id"] for i in items(st)]
            for _ in range(ids.index(target)):
                s.tap("down")
            s.tap("return")
            wait_state(s, lambda st: not st["open"], 3)
            open_with_shortcut(s)
        st = type_query(s, "kal")
        check("learns from what the owner opens: “kal” now puts the chosen app first", items(st)[0]["id"] == target,
              f"default first {first}, chosen {target}, now {items(st)[0]['id']}")
        # ---- files arrive asynchronously without moving the selection
        st = type_query(s, "rechnung fahr")
        t0 = time.monotonic()
        sel_before = st["selected"]
        st = wait_state(s, lambda st: any(r["id"].startswith("file:") for r in st["rows"]), 5)
        dt = time.monotonic() - t0
        files = [r for r in items(st) if r["id"].startswith("file:")]
        results["search_files_latency_s"] = round(dt, 3)
        check("files and folders by name arrive asynchronously (50 000-file index)", bool(files) and "Rechnung Fahrrad 2026.pdf" == files[0]["title"],
              f"{dt:.2f}s " + json.dumps([f["title"] for f in files[:3]], ensure_ascii=False))
        check("…without moving the selection", st["selected"] == sel_before, f"{sel_before} → {st['selected']}")
        # mixed results screenshot
        st = type_query(s, "rechnung")
        wait_state(s, lambda st: any(r["id"].startswith("file:") for r in st["rows"]), 5)
        time.sleep(0.6)
        save(s.screenshot(), "search-mixed-light-1.0x.png", crop=(240, 120, 1040, 700))
        # ⌘↩ (Ctrl↩) reveals the file
        fid = next(i["id"] for i in items(state(s)) if i["id"].startswith("file:"))
        select(s, fid)
        s.tap("leftctrl", "return")
        st = wait_state(s, lambda st: not st["open"], 3)
        check("Ctrl+↩ on a file shows it in Files instead of opening it", bool(st) and st["lastActivated"].startswith("file:reveal:"), st and st["lastActivated"])
        # ---- Ask: a question puts Ask first; choosing it sends `assistant ask <text>`
        open_with_shortcut(s)
        st = type_query(s, "wie wird das wetter morgen")
        its = items(st)
        check("a question puts the Ask row first", bool(its) and its[0]["id"] == "ask", json.dumps([i["id"] for i in its[:3]]))
        time.sleep(0.5)
        save(s.screenshot(), "search-ask-first-light-1.0x.png", crop=(240, 120, 1040, 560))
        st = type_query(s, "kate")
        ids = [i["id"] for i in items(st)]
        check("every query offers Ask (after the results, before the web)", ids[-2:] == ["ask", "web"], json.dumps(ids))
        st = type_query(s, "wie wird das wetter morgen")
        s.tap("return")
        ok = wait_until(lambda: 'ASSISTANT-REQUEST ["ask","wie wird das wetter morgen"' in s.shell_log(), 4)
        check("choosing Ask sends request assistant ask <text> through the shell bus", bool(ok))
        # ---- web, app, settings, action rows perform their action
        open_with_shortcut(s)
        st = type_query(s, "kate")
        s.tap("return")
        ok = wait_until(lambda: s.app_windows("org.kde.kate"), 15)
        check("↩ on an app opens it", bool(ok))
        open_with_shortcut(s)
        type_query(s, "maus")
        select(s, "set:kcm_mouse")
        s.tap("return")
        st = wait_state(s, lambda st: not st["open"], 3)
        check("↩ on a settings page opens System Settings on it", st["lastActivated"] == "settings:kcm_mouse", st["lastActivated"])
        # (a window that maps while Search is open takes the keyboard from it: KWin 6.8 behaviour,
        # see README; wait for System Settings before going on)
        wait_until(lambda: s.app_windows("systemsettings") or s.app_windows("org.kde.systemsettings"), 15)
        time.sleep(1.0)
        open_with_shortcut(s)
        st = type_query(s, "dunkelmodus")
        select(s, "act:dark")
        s.tap("return")
        ok = wait_until(lambda: '"dark"' in subprocess.run(["kristall-settings", "get", "appearance.theme"], env=dict(s.env(), **s.shell_env()),
                                                          capture_output=True, text=True).stdout, 4)
        check("action row: Dunkelmodus einschalten switches the theme", bool(ok))
        open_with_shortcut(s)
        st = type_query(s, "abcdefg")
        select(s, "web")
        s.tap("return")
        st = wait_state(s, lambda st: not st["open"], 3)
        check("the last row searches the web", st["lastActivated"].startswith("web:"), st["lastActivated"])
        # the browser it started (Firefox is in the dev image) would take the keyboard from Search
        # when its window maps: close it before going on
        time.sleep(1.5)
        subprocess.run(["pkill", "-f", "firefox"], capture_output=True)
        wait_until(lambda: not [w for w in s.windows() if w["normal"] and "firefox" in (w["appId"] or "").lower()], 8)
        time.sleep(0.5)
        # ---- latency per keystroke (synchronous part), a few hundred apps
        open_with_shortcut(s)
        type_query(s, "beispiel")
        e = json.loads(s.ipc("searchtest", "benchEngine", "beispiel studio 42", 200))
        info("matching only, µs per keystroke: " + json.dumps(e))
        results["search_engine_us"] = e
        b = json.loads(s.ipc("searchtest", "bench", "beispiel studio 42", 200))
        results["search_sync_us_per_keystroke"] = round(b["usPerKeystroke"], 1)
        check("apps + settings + actions + calculator per keystroke < 8 ms (well inside a frame)", b["usPerKeystroke"] < 8000, json.dumps(b))
        check("app matching stays synchronous and under 2 ms per keystroke (300+ apps)", e["apps"] < 2000, json.dumps(e))
        # ---- escape: clears, then closes
        s.tap("esc")
        st = wait_state(s, lambda st: st["query"] == "", 2)
        s.tap("esc")
        st = wait_state(s, lambda st: not st["open"], 2)
        check("⎋ clears the text, a second ⎋ closes", bool(st) and not st["open"])
        bad = [l for l in s.shell_log().splitlines() if ("WARN" in l or "ERROR" in l) and not any(k in l for k in ("pipewire", "quickshell.network", "upower", "powerprofiles", "bluetooth"))]
        check("zero QML warnings", not bad, "\n".join(bad[:8]))
    finally:
        s.stop()
        shutil.rmtree(tmp, ignore_errors=True)


def test_looks():
    print("== looks: dark, 1.6, without the assistant", flush=True)
    for name, settings, w, h, sc in (("dark-1.0x", {"appearance": {"theme": "dark", "glass": 0.3}}, 1280, 800, 1.0),
                                     ("light-1.6x", {"appearance": {"theme": "light", "glass": 0.3}}, 1800, 1125, 1.6)):
        tmp = tempfile.mkdtemp(prefix="kristall-search-looks-")
        shell = os.path.join(tmp, "shell")         # a shell without the assistant module
        shutil.copytree(A.SHELL, shell, ignore=shutil.ignore_patterns("tests", "evidence", "__pycache__"))
        shutil.rmtree(os.path.join(shell, "modules", "assistant"), ignore_errors=True)
        s = A.AppsSession(name="search-" + name, settings=settings, width=w, height=h, scale=sc, shell_path=shell)
        s.start()
        try:
            bg = os.path.join(s.tmp, "bg.png")
            Image.fromarray(pattern.busy(w, h)).save(bg)
            s.background(bg)
            s.start_shell()
            wait_until(lambda: "module search loaded" in s.shell_log(), 15)
            time.sleep(1.5)
            s.ipc("searchtest", "setQuery", "termin")
            st = wait_state(s, lambda st: st["open"] and st["rows"], 5)
            time.sleep(0.8)
            check(f"{name}: no Ask row without the assistant module", not any(r["id"] == "ask" for r in st["rows"]))
            img = s.screenshot()
            save(img, f"search-results-{name}.png", crop=(int(240 * sc), int(120 * sc), int((w - 240) * sc), int(620 * sc)))
            bad = [l for l in s.shell_log().splitlines() if ("WARN" in l or "ERROR" in l) and not any(k in l for k in ("pipewire", "quickshell.network", "upower", "powerprofiles", "bluetooth"))]
            check(f"{name}: zero QML warnings", not bad, "\n".join(bad[:6]))
        finally:
            s.stop()
            shutil.rmtree(tmp, ignore_errors=True)


SECTIONS = {"static": test_static, "behaviour": test_behaviour, "looks": test_looks}
if __name__ == "__main__":
    wanted = sys.argv[1:] or list(SECTIONS)
    for name in wanted:
        try:
            SECTIONS[name]()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            check(f"section {name} ran to the end", False, repr(e))
    os.makedirs(EVIDENCE, exist_ok=True)
    out = os.path.join(EVIDENCE, "results.json")
    old = json.load(open(out)) if os.path.exists(out) else {}
    old.update(results)
    old["last_run"] = {"sections": wanted, "failures": failures, "time": time.strftime("%Y-%m-%dT%H:%M:%S")}
    json.dump(old, open(out, "w"), indent=1)
    print("FAILED: " + ", ".join(failures) if failures else "ALL CHECKS PASSED", flush=True)
    sys.exit(1 if failures else 0)
