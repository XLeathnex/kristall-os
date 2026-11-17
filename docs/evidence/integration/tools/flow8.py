import re, subprocess
def cursor():
    return subprocess.run(["kristall-bridgectl", "cursor"], capture_output=True, text=True).stdout.replace("\n", "").replace(" ", "")
print("owner cursor before:", cursor())
txt, _ = call("open_app", name="Texteditor")
time.sleep(4)
txt, _ = call("ui_tree", window="KWrite")
ref = next((l.split()[0] for l in txt.splitlines() if re.search(r"New File|Neue Datei|Neu\b", l)), None)
print("New-File ref:", ref)
if ref:
    call("ui_act", ref=ref, action="press")
    time.sleep(1.5)
txt, _ = call("screenshot", target="window", window="KWrite")
m = re.search(r"(\d+)x(\d+)", txt)
# click into the middle of the editor area the way the model does from a screenshot (agent cursor visible)
if m:
    w, h = int(m.group(1)), int(m.group(2))
    call("click", x=w * 0.5, y=h * 0.6, intent="ins Textfeld klicken")
call("type_text", text="Einkaufsliste:\n- Äpfel\n- Brötchen\n- Käse aus Österreich\n- Süßigkeiten für die Kinder\n- Grüße an Jürgen", window="KWrite")
time.sleep(1)
subprocess.run(["python3", "/integ/shot.py", "08d-hands-shopping-list"])
print("owner cursor after:", cursor())
