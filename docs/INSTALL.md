# Kristall OS installieren · Installing Kristall OS

[Deutsch](#deutsch) · [English](#english)

---

## Deutsch

Diese Anleitung führt dich vom Windows-Laptop zum fertigen Kristall OS. Du brauchst keine
Vorkenntnisse und musst nie etwas eintippen außer deinem Namen und Passwort.

> **Wichtig:** Die Installation **löscht alles auf dem Laptop – auch Windows** und alle deine
> Dateien. Sichere vorher, was du behalten willst (Schritt 3).

### Was du brauchst

- den Laptop, **am Netzteil**
- einen **USB-Stick mit mindestens 16 GB**. Alles darauf wird gelöscht.
- Internet (WLAN reicht) und etwa **2 Stunden**, davon die meiste Zeit Warten
- dein GitHub-Konto (in dem das Kristall-OS-Projekt liegt)

Kleine Wörterliste:
- **ISO-Datei** – eine Datei, die den Inhalt eines Installations-Sticks enthält.
- **Boot-Menü** – eine Liste, in der der Laptop beim Einschalten fragt, wovon er starten soll.
- **UEFI / BIOS** – die Grundeinstellungen des Laptops, noch vor Windows.
- **Secure Boot** – ein Schutz, der nur geprüfte Systeme starten lässt. Kristall OS funktioniert damit; lass es eingeschaltet.

### Schritt 1 – Einmalig: das Projekt auf GitHub vorbereiten

Nur beim allerersten Mal. Öffne dein Projekt auf github.com.

1. **Projekt öffentlich machen** (sonst sind die automatischen Builds nicht kostenlos und der Laptop
   bekommt keine Updates): *Settings* → ganz unten *Danger Zone* → *Change repository visibility*
   → *Public*. Steht dort schon „Public“, ist nichts zu tun.
2. **Automatik einschalten:** Reiter *Actions*. Erscheint ein grüner Knopf
   *„I understand my workflows, go ahead and enable them“*, klicke ihn.
3. **Warten**, bis unter *Actions* der Eintrag **„Build OS image“** einen **grünen Haken** hat
   (etwa 1 Stunde). Ein rotes Kreuz? Öffne den Eintrag – oben steht in einfachen Worten, was fehlt.
4. **Das System öffentlich herunterladbar machen** (damit der Laptop später Updates holen darf):
   Klicke oben rechts auf dein Profilbild → *Your profile* → Reiter *Packages* → **kristall-os** →
   rechts *Package settings* → ganz unten *Change visibility* → **Public** → Namen zur Bestätigung
   eintippen → *I understand…*.

Danach baut GitHub den Installations-Stick-Inhalt von selbst (Eintrag **„Build installer ISO“**,
etwa 1–2 Stunden). Er startet automatisch nach Schritt 3; wenn nicht: *Actions* → links
*Build installer ISO* → rechts *Run workflow* → grüner Knopf *Run workflow*. Danach entsteht jeden
Montag ein neuer.

### Schritt 2 – Die Installationsdatei herunterladen

1. *Actions* → links **Build installer ISO** → oben der neueste Eintrag mit grünem Haken.
2. Klicke im Bereich *Summary* auf **„Download the Kristall OS installer“**
   (oder unten bei *Artifacts* auf **Kristall-OS-Installer.iso**).
3. Die Datei ist etwa 8–9 GB groß; der Download dauert je nach Internet 10–60 Minuten.
   Du musst bei GitHub angemeldet sein. Die Datei ist fertig – nichts entpacken.

### Schritt 3 – Sichern, was du behalten willst

Kopiere auf eine externe Festplatte oder in einen Online-Speicher (z. B. OneDrive, Google Drive):
- die Ordner **Dokumente, Bilder, Videos, Musik, Desktop, Downloads**
- **Browser-Lesezeichen und Passwörter** (am einfachsten: im Browser mit einem Konto synchronisieren)
- **Spielstände**, die nicht in der Cloud liegen, und **Lizenzschlüssel** gekaufter Programme
- dein **WLAN-Passwort** (steht oft auf dem Router)

Prüfe danach, ob die Kopien sich öffnen lassen. Windows lässt sich später bei Bedarf kostenlos
von Microsoft neu installieren; die Lizenz hängt am Laptop.

### Schritt 4 – Den USB-Stick erstellen (unter Windows)

Wir benutzen **Fedora Media Writer**, ein kostenloses, einfaches Programm.

1. Lade es von **fedoraproject.org/workstation/download** (Abschnitt *Fedora Media Writer* →
   *Windows*) herunter und starte es (bei der Frage „Änderungen zulassen?“: *Ja*).
2. Wähle **„Select .iso file“ / „ISO-Datei auswählen“** → *Weiter* → wähle
   **Kristall-OS-Installer.iso** aus deinem Download-Ordner.
3. Wähle unter *USB-Laufwerk* deinen Stick. **Achtung:** Alles darauf wird gelöscht.
4. Klicke **Schreiben** und warte, bis „Fertig“ erscheint (10–20 Minuten). Schließe das Programm.

Alternative: **Rufus** (rufus.ie). Wenn Rufus fragt, wie es schreiben soll, wähle
**„Im DD-Abbild-Modus schreiben“**.

### Schritt 5 – Vom USB-Stick starten

Stecke den Stick ein, das Netzteil bleibt angeschlossen.

**Weg A – über Windows (funktioniert bei fast allen Laptops):**
*Start* → *Einstellungen* → *System* → *Wiederherstellung* → bei *Erweiterter Start* auf
**Jetzt neu starten** → *Gerät verwenden* (oder *Ein Gerät verwenden*) → deinen **USB-Stick**
wählen (heißt oft „EFI USB Device“ oder nach dem Hersteller des Sticks).

**Weg B – mit einer Taste beim Einschalten:** Laptop ganz ausschalten. Einschalten und **sofort
mehrmals** die Boot-Menü-Taste drücken, bis eine Liste erscheint. Dort den USB-Stick wählen.

| Hersteller | Taste | Hersteller | Taste |
|---|---|---|---|
| Acer | F12 | Lenovo | F12 (oder kleiner „Novo“-Knopf an der Seite) |
| ASUS | Esc oder F8 | Medion | F10 oder F11 |
| Dell | F12 | MSI | F11 |
| Gigabyte / Aorus | F12 | Razer | F12 |
| HP | Esc, dann F9 | Samsung | F2 oder Esc |
| Huawei / Honor | F12 | Schenker / XMG / Tuxedo | F7 |
| Microsoft Surface | Lautstärke-leiser gedrückt halten und einschalten | Toshiba / Dynabook | F12 |

Unbekannte Marke? Achte beim Einschalten auf eine Zeile wie „Press F… for Boot Menu“ oder nimm Weg A.

### Schritt 6 – Installieren

1. Es erscheint ein schwarzes Menü. **„Kristall OS installieren (Deutsch)“** startet nach
   5 Sekunden von selbst. (Bleibt der Bildschirm danach schwarz: neu starten und
   **„einfache Grafik“** wählen.)
2. Kristall OS startet vom Stick, und das **Installationsprogramm öffnet sich von selbst**.
   Du kannst es schließen und dich erst umsehen (WLAN, Touchpad, Ton prüfen) – über das Symbol
   **„Kristall OS installieren“** öffnest du es wieder.
3. **Sprache:** *Deutsch* → *Weiter*.
4. **Installationsziel / Speicher:** Wähle die interne SSD (meist die einzige, ca. 1 TB) und
   **„Gesamte Festplatte verwenden“** („Use entire disk“). Verschlüsselung: lass das Häkchen leer
   – sonst brauchst du bei jedem Start ein zusätzliches Passwort. → *Weiter*.
5. **Überprüfen:** Lies die Zusammenfassung. Mit **„Daten löschen und installieren“** geht es los.
   Das ist der Moment, ab dem Windows und alle Dateien gelöscht werden.
6. Warte 10–30 Minuten. Am Ende: **Neu starten**. Ziehe den USB-Stick ab, wenn der Bildschirm
   schwarz wird.

Kein Konto, kein Passwort, keine Zeitzone? Richtig – das kommt beim ersten Start.

### Schritt 7 – Der erste Start

1. Ein Begrüßungs-Assistent fragt nach **Sprache, Tastatur, Zeitzone, WLAN** und legt **dein
   Benutzerkonto** an (Name, Passwort – merke es dir gut, es ist auch das Administrator-Passwort).
2. Danach bist du direkt angemeldet und der **Kristall Einrichtungsassistent** übernimmt
   (Aussehen, Anmeldung bei Claude für den Assistenten und mehr).
3. Im Hintergrund werden deine Apps installiert – oben siehst du z. B.
   „Deine Apps werden installiert … 4 von 10“. Das braucht Internet; ohne Internet geht es später
   von selbst weiter.

### Updates

Kristall OS aktualisiert sich selbst im Hintergrund (nicht im mobilen Hotspot, nicht bei fast
leerem Akku). Ist ein Update bereit, erscheint **„Update bereit“** – starte neu, wann es dir passt.
Nichts wird während deiner Arbeit verändert. Wenn nach einem Update etwas nicht stimmt: in den
Einstellungen **„Vorherige Version“** wählen und neu starten.

### Wenn etwas nicht klappt

- **Der Laptop startet trotzdem Windows:** Weg A in Schritt 5 benutzen, oder einen anderen
  USB-Anschluss versuchen.
- **„Secure Boot Violation“ o. ä.:** Sollte nicht vorkommen (Kristall OS ist für Secure Boot
  signiert). Notiere die Meldung und den Laptop-Typ und melde es im Projekt unter *Issues*.
- **Das Installationsprogramm findet keine Festplatte:** Manche Laptops verstecken die SSD hinter
  „Intel RST / VMD“. Im UEFI (beim Einschalten F2 oder Entf) die Einstellung *VMD Controller* bzw.
  *SATA/Storage Mode* auf **AHCI/NVMe** stellen. (Windows startet danach nicht mehr – egal, es wird
  ohnehin ersetzt.)
- **Windows behalten (für Fortgeschrittene, nicht empfohlen):** In Windows unter
  *Datenträgerverwaltung* die Windows-Partition verkleinern (mindestens 100 GB frei lassen), dann
  in Schritt 6.4 **„Festplatte mit anderem Betriebssystem teilen“** wählen.

---

## English

This guide takes you from a Windows laptop to a working Kristall OS. You need no prior knowledge
and never have to type anything except your name and password.

> **Important:** Installing **erases everything on the laptop – including Windows** and all your
> files. Back up what you want to keep first (step 3).

### What you need

- the laptop, **plugged into its charger**
- a **USB stick of at least 16 GB**. Everything on it will be erased.
- internet (Wi-Fi is fine) and about **2 hours**, mostly waiting
- your GitHub account (where the Kristall OS project lives)

Small glossary:
- **ISO file** – one file that holds the contents of an installation stick.
- **Boot menu** – a list where the laptop asks, when switched on, what to start from.
- **UEFI / BIOS** – the laptop's basic settings, before Windows starts.
- **Secure Boot** – a protection that only starts verified systems. Kristall OS works with it; leave it on.

### Step 1 – Once: prepare the project on GitHub

Only the very first time. Open your project on github.com.

1. **Make the project public** (otherwise the automatic builds are not free and the laptop cannot
   get updates): *Settings* → at the bottom *Danger Zone* → *Change repository visibility* →
   *Public*. If it already says "Public", nothing to do.
2. **Switch the automation on:** tab *Actions*. If a green button
   *"I understand my workflows, go ahead and enable them"* appears, click it.
3. **Wait** until under *Actions* the entry **"Build OS image"** has a **green tick**
   (about 1 hour). A red cross? Open it – the top says in plain words what is missing.
4. **Make the system downloadable** (so the laptop may fetch updates later): click your profile
   picture (top right) → *Your profile* → tab *Packages* → **kristall-os** → *Package settings*
   (right) → at the bottom *Change visibility* → **Public** → type the name to confirm →
   *I understand…*.

GitHub then builds the installer by itself (entry **"Build installer ISO"**, about 1–2 hours). It
starts automatically after step 3; if not: *Actions* → left *Build installer ISO* → right
*Run workflow* → green *Run workflow* button. A new one is made every Monday.

### Step 2 – Download the installer file

1. *Actions* → left **Build installer ISO** → the newest entry with a green tick.
2. In the *Summary* click **"Download the Kristall OS installer"**
   (or at the bottom under *Artifacts* click **Kristall-OS-Installer.iso**).
3. The file is about 8–9 GB; downloading takes 10–60 minutes depending on your internet.
   You must be signed in to GitHub. The file is ready to use – nothing to unzip.

### Step 3 – Back up what you want to keep

Copy to an external drive or cloud storage (e.g. OneDrive, Google Drive):
- the folders **Documents, Pictures, Videos, Music, Desktop, Downloads**
- **browser bookmarks and passwords** (easiest: sync them with an account in the browser)
- **game saves** that are not in the cloud, and **licence keys** of software you bought
- your **Wi-Fi password** (often printed on the router)

Then check that the copies open. Windows can be reinstalled later for free from Microsoft if
ever needed; the licence belongs to the laptop.

### Step 4 – Make the USB stick (on Windows)

We use **Fedora Media Writer**, a free, simple program.

1. Download it from **fedoraproject.org/workstation/download** (section *Fedora Media Writer* →
   *Windows*) and run it (answer *Yes* to "allow changes?").
2. Choose **"Select .iso file"** → *Next* → pick **Kristall-OS-Installer.iso** from your
   Downloads folder.
3. Under *USB Drive* choose your stick. **Careful:** everything on it is erased.
4. Click **Write** and wait for "Finished" (10–20 minutes). Close the program.

Alternative: **Rufus** (rufus.ie). If Rufus asks how to write, choose **"Write in DD Image mode"**.

### Step 5 – Start from the USB stick

Plug the stick in; keep the charger connected.

**Way A – through Windows (works on almost every laptop):**
*Start* → *Settings* → *System* → *Recovery* → next to *Advanced startup* click **Restart now** →
*Use a device* → choose your **USB stick** (often called "EFI USB Device" or by the stick's brand).

**Way B – with a key at power-on:** switch the laptop off completely. Switch it on and **right
away press the boot-menu key repeatedly** until a list appears. Choose the USB stick.

| Brand | Key | Brand | Key |
|---|---|---|---|
| Acer | F12 | Lenovo | F12 (or the small "Novo" button on the side) |
| ASUS | Esc or F8 | Medion | F10 or F11 |
| Dell | F12 | MSI | F11 |
| Gigabyte / Aorus | F12 | Razer | F12 |
| HP | Esc, then F9 | Samsung | F2 or Esc |
| Huawei / Honor | F12 | Schenker / XMG / Tuxedo | F7 |
| Microsoft Surface | hold Volume Down while switching on | Toshiba / Dynabook | F12 |

Unknown brand? Watch for a line like "Press F… for Boot Menu" at power-on, or use way A.

### Step 6 – Install

1. A black menu appears. Choose **"Install Kristall OS (English)"** (the German entry starts by
   itself after 5 seconds). If the screen stays black afterwards: restart and choose
   **"basic graphics"**.
2. Kristall OS starts from the stick and the **installer opens by itself**. You may close it and
   look around first (check Wi-Fi, touchpad, sound) – the **"Install Kristall OS"** icon opens it again.
3. **Language:** *English* (or *Deutsch*) → *Next*.
4. **Installation destination / storage:** choose the internal SSD (usually the only one, about
   1 TB) and **"Use entire disk"**. Encryption: leave it unticked – otherwise you need an extra
   password at every start. → *Next*.
5. **Review:** read the summary. **"Erase data and install"** starts it. This is the moment
   Windows and all files are deleted.
6. Wait 10–30 minutes. At the end: **Reboot**. Pull out the USB stick when the screen goes black.

No account, password or time zone asked? Correct – that comes at first start.

### Step 7 – First start

1. A welcome assistant asks for **language, keyboard, time zone, Wi-Fi** and creates **your user
   account** (name, password – remember it, it is also the administrator password).
2. You are then signed in directly and the **Kristall Setup Assistant** takes over (look, signing
   in to Claude for the assistant, and more).
3. Your apps are installed in the background – you will see e.g. "Installing your apps… 4 of 10".
   This needs internet; without it, it continues by itself later.

### Updates

Kristall OS updates itself in the background (not on a mobile hotspot, not with an almost empty
battery). When an update is ready you see **"Update ready"** – restart whenever it suits you.
Nothing changes while you work. If something is wrong after an update: choose
**"Previous version"** in the settings and restart.

### If something goes wrong

- **The laptop still starts Windows:** use way A in step 5, or try another USB port.
- **"Secure Boot Violation" or similar:** should not happen (Kristall OS is signed for Secure
  Boot). Note the message and laptop model and report it in the project under *Issues*.
- **The installer finds no disk:** some laptops hide the SSD behind "Intel RST / VMD". In the UEFI
  (F2 or Del at power-on) set *VMD Controller* or *SATA/Storage Mode* to **AHCI/NVMe**. (Windows
  will not start any more after that – fine, it is being replaced anyway.)
- **Keep Windows (advanced, not recommended):** in Windows' *Disk Management* shrink the Windows
  partition (leave at least 100 GB free), then in step 6.4 choose
  **"Share disk with other operating system"**.

---

<sub>For maintainers: what happens behind these steps is described in `image/README.md`
(image pipeline), `image/iso/` (installer) and `docs/contracts/update.md` (updates).
Installer = Titanoboa live ISO with Anaconda; the OS image and the free default apps travel on
the stick, proprietary apps (VS Code, Steam, Sober) are downloaded on first start.</sub>
