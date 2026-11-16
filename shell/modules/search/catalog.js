// SPDX-License-Identifier: GPL-3.0-or-later
// What Search knows besides apps and files: System Settings pages by the words a person would
// use (German and English), system actions, and how to tell a question or request (→ Ask).
.pragma library

// kcm: System Settings module id (shown only when its desktop file exists on this machine)
const SETTINGS = [
    { kcm: "kcm_networkmanagement", en: "Wi-Fi & Network", de: "WLAN & Netzwerk", sym: "wifi-high",
      kw: "wlan wifi wi-fi wireless network netzwerk internet ethernet lan vpn hotspot" },
    { kcm: "kcm_bluetooth", en: "Bluetooth", de: "Bluetooth", sym: "bluetooth", kw: "bluetooth kopfhörer headphones maus" },
    { kcm: "kcm_kscreen", en: "Displays", de: "Bildschirme", sym: "monitor",
      kw: "display displays bildschirm monitor auflösung resolution skalierung scale helligkeit brightness night nachtmodus" },
    { kcm: "kcm_nightlight", en: "Night Shift", de: "Night Shift", sym: "moon", kw: "nacht night blaulicht farbtemperatur" },
    { kcm: "kcm_pulseaudio", en: "Sound", de: "Ton", sym: "speaker-high", kw: "ton sound audio lautstärke volume lautsprecher speaker mikrofon microphone" },
    { kcm: "kcm_mouse", en: "Mouse", de: "Maus", sym: "mouse", kw: "maus mouse zeiger pointer scrollen" },
    { kcm: "kcm_touchpad", en: "Trackpad", de: "Trackpad", sym: "hand-pointing", kw: "trackpad touchpad gesten gestures tippen tap" },
    { kcm: "kcm_keyboard", en: "Keyboard", de: "Tastatur", sym: "keyboard", kw: "tastatur keyboard layout tastaturbelegung sprache eingabe" },
    { kcm: "kcm_keys", en: "Keyboard Shortcuts", de: "Tastaturkurzbefehle", sym: "command", kw: "kurzbefehle shortcuts tastenkürzel hotkeys" },
    { kcm: "kcm_powerdevilprofilesconfig", en: "Battery", de: "Batterie", sym: "battery-high",
      kw: "batterie battery energie energy akku strom power energiesparen ruhezustand" },
    { kcm: "kcm_wallpaper", en: "Wallpaper", de: "Hintergrundbild", sym: "image", kw: "hintergrund wallpaper desktop schreibtisch bild" },
    { kcm: "kcm_colors", en: "Appearance", de: "Erscheinungsbild", sym: "palette", kw: "erscheinungsbild appearance dunkel dark hell light farbe color akzent accent" },
    { kcm: "kcm_fonts", en: "Fonts", de: "Schriften", sym: "text-aa", kw: "schrift schriften fonts font" },
    { kcm: "kcm_notifications", en: "Notifications", de: "Mitteilungen", sym: "bell", kw: "mitteilungen notifications benachrichtigungen" },
    { kcm: "kcm_regionandlang", en: "Language & Region", de: "Sprache & Region", sym: "globe", kw: "sprache language region format datum zahlen" },
    { kcm: "kcm_clock", en: "Date & Time", de: "Datum & Uhrzeit", sym: "clock", kw: "datum uhrzeit date time zeitzone timezone uhr" },
    { kcm: "kcm_users", en: "Users & Groups", de: "Benutzer:innen & Gruppen", sym: "users", kw: "benutzer user users konto account passwort password" },
    { kcm: "kcm_access", en: "Accessibility", de: "Bedienungshilfen", sym: "person", kw: "bedienungshilfen barrierefreiheit accessibility zoom vorlesen" },
    { kcm: "kcm_screenlocker", en: "Lock Screen", de: "Sperrbildschirm", sym: "lock", kw: "sperrbildschirm lock screen sperren passwort" },
    { kcm: "kcm_printer_manager", en: "Printers", de: "Drucker", sym: "printer", kw: "drucker printer drucken print scanner" },
    { kcm: "kcm_componentchooser", en: "Default Apps", de: "Standard-Apps", sym: "app-window", kw: "standard default apps browser e-mail" },
    { kcm: "kcm_autostart", en: "Login Items", de: "Anmeldeobjekte", sym: "sign-in", kw: "autostart anmeldeobjekte login startup" },
    { kcm: "kcm_baloofile", en: "File Search", de: "Dateisuche", sym: "magnifying-glass", kw: "suche search index dateisuche spotlight" },
    { kcm: "kcm_trash", en: "Trash", de: "Papierkorb", sym: "trash", kw: "papierkorb trash" }
];

// actions: {id, en, de, sym, kw}; run by the module (Session, settings, bridge)
const ACTIONS = [
    { id: "lock", en: "Lock Screen", de: "Bildschirm sperren", sym: "lock", kw: "sperren lock bildschirm screen" },
    { id: "sleep", en: "Sleep", de: "Ruhezustand", sym: "moon", kw: "ruhezustand schlafen sleep standby suspend" },
    { id: "restart", en: "Restart …", de: "Neustart …", sym: "arrow-clockwise", kw: "neustart neu starten restart reboot" },
    { id: "shutdown", en: "Shut Down …", de: "Ausschalten …", sym: "power", kw: "ausschalten herunterfahren shut down shutdown power off" },
    { id: "logout", en: "Log Out …", de: "Abmelden …", sym: "sign-out", kw: "abmelden log out logout" },
    { id: "dark", en: "Dark Mode", de: "Dunkelmodus", sym: "circle-half", kw: "dunkelmodus dark mode dunkel hell light mode erscheinungsbild" },
    { id: "dnd", en: "Do Not Disturb", de: "Nicht stören", sym: "moon-stars", kw: "nicht stören do not disturb dnd focus fokus ruhe" },
    { id: "overview", en: "Overview", de: "Übersicht", sym: "squares-four", kw: "übersicht overview alle fenster all windows mission" },
    { id: "desktop", en: "Show Desktop", de: "Schreibtisch anzeigen", sym: "desktop", kw: "schreibtisch desktop anzeigen show" }
];

// a question or a request for the assistant (German and English)
const QUESTION_START = /^(wer|wen|wem|wessen|was|wann|wo|woher|wohin|wie|warum|wieso|weshalb|welche[rsmn]?|kann|kannst|könnte|könntest|sollte|soll|ist|sind|gibt|hast|habe|bist|darf|muss|würde|erkläre|erklär|schreib|schreibe|erstelle|mach|mache|zeig mir|hilf|hilfe|bitte|fasse|übersetze|plane|finde heraus|who|whom|whose|what|when|where|why|how|which|can|could|would|should|shall|is|are|was|were|do|does|did|will|please|make|write|create|explain|help|tell|show me|summarize|summarise|translate|plan|draft|find out)\b/i;

function isQuestion(text) {
    const t = String(text || "").trim();
    if (t.length < 3)
        return false;
    if (/\?\s*$/.test(t))
        return true;
    const words = t.split(/\s+/);
    return (QUESTION_START.test(t) && words.length >= 2) || words.length >= 6;
}
