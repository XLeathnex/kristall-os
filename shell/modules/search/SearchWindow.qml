// SPDX-License-Identifier: GPL-3.0-or-later
// "Search or Ask" on one output: a centred glass capsule that grows into a results list while
// typing. Full-output Overlay surface (namespace "kristall-search"; a click outside closes),
// exclusive keyboard while open.
//
// Results, best first: Ask (first when the text reads as a question or request), Top Hit, Apps,
// Calculator / Conversion, System Settings, Actions, Files & Folders (asynchronous, from the
// system's file index), Ask, Web. Apps, settings, actions and calculations are computed
// synchronously on every keystroke (well within a frame); files arrive later and are inserted
// below them, and the selection follows its item, so nothing the owner is about to press moves.
// Keys: ↑↓ select, ↩ open, ⌘↩ / Ctrl↩ show a file in Files, ⎋ clears, then closes.
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.core
import qs.services
import "calc.js" as Calc
import "catalog.js" as Catalog
import "../../core/fuzzy.js" as Fuzzy

PanelWindow {
    id: searchWindow
    property string initialQuery: ""
    signal closeRequested()
    signal activated(string what)
    readonly property string screenName: screen ? screen.name : ""

    WlrLayershell.namespace: "kristall-search"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"

    // ---- metrics ----------------------------------------------------------------------------
    readonly property real panelW: Math.min(680, width - 2 * Theme.space.huge)
    readonly property real fieldH: 52
    readonly property real rowH: 36
    readonly property real headerH: 26
    readonly property real maxListH: Math.min(9 * rowH + 2 * headerH, height * 0.62 - fieldH)

    property real shown: 0
    onInitialQueryChanged: if (shown > 0) input.text = initialQuery
    Behavior on shown { NumberAnimation { duration: Theme.duration("short", true); easing.type: Easing.OutQuad } }
    Component.onCompleted: {
        shown = 1;
        input.text = initialQuery;
        Qt.callLater(() => input.forceActiveFocus());
    }

    // ---- sources ----------------------------------------------------------------------------
    readonly property bool assistantPresent: ShellBus.handled["assistant"] === true
    readonly property string query: input.text
    property var rows: []            // [{id, kind: header|item, …}]
    property var fileRows: []        // last file results for fileQuery
    property string fileQuery: ""
    property string selectedId: ""
    property real lastSearchMs: 0

    function _settingsRows(q) {
        const out = [];
        const qq = Fuzzy.query(q);
        if (qq.q.length < 2)
            return out;
        for (const s of Catalog.SETTINGS) {
            if (!s._p)
                s._p = Fuzzy.prepare([{ text: s.de, weight: 1 }, { text: s.en, weight: 1 }, { text: s.kw, weight: 0.85 }]);
            const sc = Fuzzy.score(s._p, qq.q, qq.w);
            if (sc > 0 && DesktopEntries.byId(s.kcm))
                out.push({ score: sc, row: { id: "set:" + s.kcm, kind: "item", type: "settings", title: Strings.pick(s), subtitle: Strings.t("search.settingsSubtitle"), sym: s.sym, kcm: s.kcm } });
        }
        return out.sort((a, b) => b.score - a.score).slice(0, 3).map(x => x.row);
    }
    function _actionRows(q) {
        const out = [];
        const qq = Fuzzy.query(q);
        if (qq.q.length < 3)
            return out;
        for (const a of Catalog.ACTIONS) {
            if (!a._p)
                a._p = Fuzzy.prepare([{ text: a.de, weight: 1 }, { text: a.en, weight: 1 }, { text: a.kw, weight: 0.85 }]);
            const sc = Fuzzy.score(a._p, qq.q, qq.w);
            if (sc <= 0)
                continue;
            let title = Strings.pick(a);
            if (a.id === "dark")
                title = Theme.dark ? Strings.t("search.darkOff") : Strings.t("search.darkOn");
            else if (a.id === "dnd")
                title = dndOn ? Strings.t("search.dndOff") : Strings.t("search.dndOn");
            out.push({ score: sc, row: { id: "act:" + a.id, kind: "item", type: "action", title: title, subtitle: Strings.t("search.actionSubtitle"), sym: a.sym, action: a.id } });
        }
        return out.sort((a, b) => b.score - a.score).slice(0, 3).map(x => x.row);
    }
    readonly property bool dndOn: {
        const u = Number(Settings.get("panels.focus.until", 0)) || 0;
        return u === -1 || u > Date.now();
    }

    function compute(q) {
        const t0 = Date.now();
        const text = q.trim();
        const out = [];
        if (text === "") {
            rows = [];
            _publish([]);
            lastSearchMs = 0;
            return;
        }
        const header = (id, label) => out.push({ id: "h:" + id, kind: "header", title: label });
        const question = Catalog.isQuestion(text);
        const askRow = { id: "ask", kind: "item", type: "ask", title: Strings.t("search.askRow", { q: text }), subtitle: Strings.t("search.askSubtitle"), sym: "kristall/assistant" };
        if (assistantPresent && question) {
            header("ask", Strings.t("search.ask"));
            out.push(askRow);
        }
        // calculator / conversion: the answer is the top hit
        const v = Calc.evaluate(text);
        const conv = v === null ? Calc.convert(text) : null;
        if (v !== null) {
            header("calc", Strings.t("search.calc"));
            const shown = Calc.format(v, Strings.lang);
            out.push({ id: "calc", kind: "item", type: "calc", title: "= " + shown, subtitle: text + " · " + Strings.t("search.copyHint"), sym: "calculator", value: shown });
        } else if (conv) {
            header("calc", Strings.t("search.convert"));
            const shown = Calc.format(conv.value, Strings.lang) + " " + conv.to;
            out.push({ id: "calc", kind: "item", type: "calc", title: "= " + shown,
                       subtitle: Calc.format(conv.amount, Strings.lang) + " " + conv.from + " · " + Strings.t("search.copyHint"), sym: "arrows-left-right", value: shown });
        }
        const apps = AppCatalog.search(text, 8);
        const appRow = r => ({ id: "app:" + r.rec.key, kind: "item", type: "app", title: r.rec.name,
                               subtitle: AppCatalog.isRunning(r.rec.key) ? Strings.t("search.running") : Strings.t("search.appSubtitle"),
                               icon: AppCatalog.iconFor(r.rec.key), key: r.rec.key });
        let rest = apps;
        if (apps.length && v === null && !conv) {
            header("top", Strings.t("search.topHit"));
            out.push(appRow(apps[0]));
            rest = apps.slice(1);
        }
        if (rest.length) {
            header("apps", Strings.t("search.apps"));
            for (const r of rest.slice(0, 5))
                out.push(appRow(r));
        }
        const sets = _settingsRows(text);
        if (sets.length) {
            header("settings", Strings.t("search.settings"));
            for (const r of sets)
                out.push(r);
        }
        const acts = _actionRows(text);
        if (acts.length) {
            header("actions", Strings.t("search.actions"));
            for (const r of acts)
                out.push(r);
        }
        _syncRows = out;
        _assemble(text, true);
        lastSearchMs = Date.now() - t0;
        files.request(text);
    }
    property var _syncRows: []
    // synchronous rows + files (when they match the text) + Ask + Web
    function _assemble(text, fresh) {
        const out = _syncRows.slice();
        if (fileQuery === text && fileRows.length) {
            out.push({ id: "h:files", kind: "header", title: Strings.t("search.files") });
            for (const r of fileRows)
                out.push(r);
        }
        if (assistantPresent && !Catalog.isQuestion(text)) {
            out.push({ id: "h:ask", kind: "header", title: Strings.t("search.ask") });
            out.push({ id: "ask", kind: "item", type: "ask", title: Strings.t("search.askRow", { q: text }), subtitle: Strings.t("search.askSubtitle"), sym: "kristall/assistant" });
        }
        out.push({ id: "h:web", kind: "header", title: Strings.t("search.web") });
        out.push({ id: "web", kind: "item", type: "web", title: Strings.t("search.webRow", { q: text }), subtitle: Strings.t("search.webSubtitle"), sym: "globe" });
        const firstItem = out.find(r => r.kind === "item");
        // a new text selects the best result; rows arriving later never take the selection away
        const keep = selectedId !== "" && out.some(r => r.id === selectedId) && (_userMoved || !fresh);
        rows = out;
        _publish(out);
        if (!keep)
            selectedId = firstItem ? firstItem.id : "";
        list.positionSelected();
    }
    property bool _userMoved: false
    // the list's model is updated in place: delegates are reused, not rebuilt per keystroke
    ListModel { id: rowModel }
    function _publish(out) {
        for (let i = 0; i < out.length; ++i) {
            const r = out[i];
            const v = { rid: r.id, kind: r.kind, type: r.type || "", title: r.title || "", subtitle: r.subtitle || "", icon: r.icon || "", sym: r.sym || "" };
            if (i < rowModel.count) {
                const o = rowModel.get(i);
                if (o.rid !== v.rid || o.title !== v.title || o.subtitle !== v.subtitle || o.icon !== v.icon || o.sym !== v.sym || o.kind !== v.kind)
                    rowModel.set(i, v);
            } else {
                rowModel.append(v);
            }
        }
        if (rowModel.count > out.length)
            rowModel.remove(out.length, rowModel.count - out.length);
    }
    onQueryChanged: {
        _userMoved = false;
        _keyAt = Date.now();
        compute(query);
        _awaitFrame = true;
    }
    // key → frame measurement (test hooks read it): when the text changed, and when the frame that
    // shows the new results was presented
    property real _keyAt: 0
    property bool _awaitFrame: false
    property var frameLog: []                   // [{q, keyAt, frameAt}] (wall-clock ms), last 64
    Connections {
        target: searchWindow.contentItem ? searchWindow.contentItem.Window.window : null
        function onFrameSwapped() {
            if (!searchWindow._awaitFrame)
                return;
            searchWindow._awaitFrame = false;
            searchWindow.frameLog = searchWindow.frameLog.concat([{ q: searchWindow.query, keyAt: searchWindow._keyAt, frameAt: Date.now() }]).slice(-64);
        }
    }

    // ---- files: the system's file index (Baloo, file names only), off the UI thread ----------------
    // A query runs in its own process (baloosearch6) 60 ms after typing pauses; a newer query
    // cancels the running one (its process is stopped and whatever it still prints is ignored);
    // results stream in as the process prints them (coalesced to one list update per frame).
    QtObject {
        id: files
        readonly property var cmd: (Quickshell.env("KRISTALL_SEARCH_FILES_CMD") || "baloosearch6").split(" ")
        property string pending: ""
        property int gen: 0
        property var proc: null
        function request(text) {
            pending = text;
            gen++;
            cancel();
            if (text.length < 2) {
                fileTimer.stop();
                searchWindow.fileRows = [];
                searchWindow.fileQuery = text;
                return;
            }
            fileTimer.restart();
        }
        function cancel() {
            if (proc) {
                const p = proc;
                proc = null;
                p.gen = -1;
                p.running = false;
                p.destroy(1000);          // a queued stream update may still run: it is ignored (gen)
            }
        }
        function start() {
            cancel();
            proc = fileProcComp.createObject(searchWindow, { forQuery: pending, gen: gen, command: cmd.concat(["-l", "40", pending]) });
            proc.running = true;
        }
    }
    Timer {
        id: fileTimer
        interval: 60
        onTriggered: files.start()
    }
    Component {
        id: fileProcComp
        Process {
            id: fp
            property string forQuery: ""
            property int gen: 0
            property var lines: []
            property bool _queued: false
            function flush() {
                _queued = false;
                if (gen === files.gen && gen >= 0)
                    searchWindow._filesArrived(forQuery, lines);
            }
            stdout: SplitParser {
                onRead: l => {
                    if (fp.gen !== files.gen || !l.startsWith("/"))
                        return;
                    fp.lines.push(l);
                    if (!fp._queued) {
                        fp._queued = true;
                        Qt.callLater(fp.flush);
                    }
                }
            }
            onExited: (code, status) => {
                if (gen === files.gen)
                    flush();
            }
        }
    }
    function _fileIcon(path) {
        const ext = (path.match(/\.([A-Za-z0-9]+)$/) || [, ""])[1].toLowerCase();
        const map = { pdf: "application-pdf", png: "image-x-generic", jpg: "image-x-generic", jpeg: "image-x-generic", gif: "image-x-generic",
                      webp: "image-x-generic", svg: "image-svg+xml", mp4: "video-x-generic", mkv: "video-x-generic", webm: "video-x-generic",
                      mp3: "audio-x-generic", ogg: "audio-x-generic", flac: "audio-x-generic", wav: "audio-x-generic", zip: "application-zip",
                      txt: "text-plain", md: "text-markdown", py: "text-x-python", js: "text-javascript", html: "text-html",
                      doc: "x-office-document", docx: "x-office-document", odt: "x-office-document", xls: "x-office-spreadsheet",
                      xlsx: "x-office-spreadsheet", ods: "x-office-spreadsheet", ppt: "x-office-presentation", pptx: "x-office-presentation",
                      blend: "application-x-blender", rbxl: "application-octet-stream" };
        return AppCatalog.iconUrl(ext === "" ? "folder" : (map[ext] || "text-x-generic"));
    }
    function _filesArrived(text, paths) {
        const home = Quickshell.env("HOME");
        const qq = Fuzzy.query(text);
        const scored = [];
        for (const p of paths) {
            if (/\/\./.test(p.substring(home.length)))
                continue;               // hidden files and folders
            const name = p.substring(p.lastIndexOf("/") + 1);
            const sc = Fuzzy.score(Fuzzy.prepare([{ text: name, weight: 1 }]), qq.q, qq.w) || 100;
            scored.push({ p: p, name: name, sc: sc - p.split("/").length });
        }
        scored.sort((a, b) => b.sc - a.sc);
        fileRows = scored.slice(0, 6).map(x => ({
            id: "file:" + x.p, kind: "item", type: "file", title: x.name,
            subtitle: x.p.substring(0, x.p.lastIndexOf("/")).replace(home, "~"), icon: _fileIcon(x.name), path: x.p
        }));
        fileQuery = text;
        if (text === query.trim())
            _assemble(text, false);
    }

    // ---- choosing ------------------------------------------------------------------------------
    function selectedIndex() {
        return rows.findIndex(r => r.id === selectedId);
    }
    function move(d) {
        const items = rows.filter(r => r.kind === "item");
        if (!items.length)
            return;
        let i = items.findIndex(r => r.id === selectedId);
        i = Math.max(0, Math.min(items.length - 1, i + d));
        selectedId = items[i].id;
        _userMoved = true;
        list.positionSelected();
    }
    function activate(row, reveal) {
        if (!row)
            return;
        const text = query.trim();
        switch (row.type) {
        case "app":
            AppCatalog.notePick(row.key, text);
            AppCatalog.activate(row.key);
            break;
        case "settings":
            Session.openSystemSettings(row.kcm);
            break;
        case "calc":
            Quickshell.clipboardText = row.value.replace(/\s.*$/, "");
            break;
        case "action":
            runAction(row.action);
            break;
        case "file":
            if (reveal)
                Quickshell.execDetached(["gdbus", "call", "--session", "--dest", "org.freedesktop.FileManager1", "--object-path", "/org/freedesktop/FileManager1",
                                         "--method", "org.freedesktop.FileManager1.ShowItems", "['file://" + encodeURI(row.path).replace(/'/g, "%27") + "']", ""]);
            else
                Quickshell.execDetached(["xdg-open", row.path]);
            break;
        case "ask":
            ShellBus.request("assistant", "ask", text, screenName);
            break;
        case "web":
            if (DesktopEntries.byId("org.mozilla.firefox") || DesktopEntries.byId("firefox"))
                Quickshell.execDetached(["firefox", "--search", text]);
            else
                Quickshell.execDetached(["xdg-open", "https://duckduckgo.com/?q=" + encodeURIComponent(text)]);
            break;
        }
        activated(row.type + (reveal ? ":reveal" : "") + ":" + (row.key || row.kcm || row.action || row.path || row.value || text));
        closeRequested();
    }
    function runAction(id) {
        switch (id) {
        case "lock": Session.lock(); break;
        case "sleep": Session.sleep(); break;
        case "restart": Session.restart(); break;
        case "shutdown": Session.shutDown(); break;
        case "logout": Session.logOut(); break;
        case "dark": Settings.set("appearance.theme", Theme.dark ? "light" : "dark"); break;
        case "dnd": Settings.set("panels.focus.until", dndOn ? 0 : -1); break;
        case "overview": Bridge.call("effect.toggle", { name: "overview" }); break;
        case "desktop": Bridge.call("workspace.showDesktop", { value: true }); break;
        }
    }

    // ---- surface --------------------------------------------------------------------------------
    GlassSurface {
        id: gs
        key: "search-" + searchWindow.screenName
        layerNamespace: "kristall-search"
        output: searchWindow.screenName
    }
    MouseArea {
        anchors.fill: parent
        onPressed: searchWindow.closeRequested()
    }
    readonly property real listH: {
        let h = 0;
        for (const r of rows)
            h += r.kind === "header" ? headerH : rowH;
        return rows.length ? Math.min(maxListH, h + Theme.space.m * 2) : 0;
    }
    property real animatedH: fieldH + listH
    Behavior on animatedH { NumberAnimation { duration: Theme.duration("short"); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.curve("smooth") } }

    GlassShape {
        id: panel
        shapeId: "search"
        surface: gs
        role: "panel"
        radius: Theme.radius.panel
        x: Math.round((searchWindow.width - width) / 2)
        y: Math.round(searchWindow.height * 0.22)
        width: searchWindow.panelW
        height: searchWindow.animatedH
        glassOpacity: searchWindow.shown
        opacity: searchWindow.shown
        clip: true
        MouseArea { anchors.fill: parent }        // clicks on the panel stay here

        KIcon {
            x: 18
            y: (searchWindow.fieldH - height) / 2
            size: 22
            name: "magnifying-glass"
            color: Theme.color(panel.scheme, "secondaryLabel")
        }
        TextInput {
            id: input
            x: 52
            width: parent.width - x - 48
            height: searchWindow.fieldH
            verticalAlignment: TextInput.AlignVCenter
            font.family: Theme.type.title1.family
            font.pixelSize: Theme.type.title1.size
            font.letterSpacing: Theme.type.title1.tracking
            color: Theme.color(panel.scheme, "label")
            selectionColor: Qt.alpha(Theme.accentFor(panel.scheme), 0.35)
            selectedTextColor: Theme.color(panel.scheme, "label")
            renderType: Text.NativeRendering
            clip: true
            focus: true
            Accessible.role: Accessible.EditableText
            Accessible.name: placeholder.text
            KText {
                id: placeholder
                anchors.verticalCenter: parent.verticalCenter
                visible: input.text === "" && !input.preeditText
                text: searchWindow.assistantPresent ? Strings.t("search.placeholderAsk") : Strings.t("search.placeholder")
                textStyle: "title1"
                level: "tertiaryLabel"
                scheme: panel.scheme
            }
            Keys.onPressed: ev => {
                switch (ev.key) {
                case Qt.Key_Down:
                    searchWindow.move(1);
                    break;
                case Qt.Key_Up:
                    searchWindow.move(-1);
                    break;
                case Qt.Key_Tab:
                    searchWindow.move(ev.modifiers & Qt.ShiftModifier ? -1 : 1);
                    break;
                case Qt.Key_Return:
                case Qt.Key_Enter:
                    searchWindow.activate(searchWindow.rows[searchWindow.selectedIndex()], (ev.modifiers & (Qt.ControlModifier | Qt.MetaModifier)) !== 0);
                    break;
                case Qt.Key_Escape:
                    if (input.text !== "")
                        input.text = "";
                    else
                        searchWindow.closeRequested();
                    break;
                default:
                    return;
                }
                ev.accepted = true;
            }
        }
        Rectangle {        // clear button
            visible: input.text !== ""
            width: 18; height: 18; radius: 9
            x: parent.width - 34
            y: (searchWindow.fieldH - height) / 2
            color: Theme.color(panel.scheme, "tertiaryLabel")
            KIcon { anchors.centerIn: parent; size: 10; name: "bold/x"; color: panel.scheme === "dark" ? "#000000" : "#FFFFFF" }
            TapHandler { onTapped: { input.text = ""; input.forceActiveFocus(); } }
        }
        KSeparator {
            visible: searchWindow.rows.length > 0
            y: searchWindow.fieldH
            x: 12
            width: parent.width - 24
            scheme: panel.scheme
        }

        ListView {
            id: list
            x: Theme.space.m
            y: searchWindow.fieldH + Theme.space.m
            width: parent.width - 2 * Theme.space.m
            height: Math.max(0, searchWindow.listH - 2 * Theme.space.m)
            clip: true
            model: rowModel
            boundsBehavior: Flickable.StopAtBounds
            interactive: contentHeight > height
            function positionSelected() {
                const i = searchWindow.selectedIndex();
                if (i < 0)
                    return;
                Qt.callLater(() => {
                    // keep the section header visible above the first row of a section
                    const before = i > 0 && searchWindow.rows[i - 1].kind === "header" ? i - 1 : i;
                    list.positionViewAtIndex(before, ListView.Contain);
                    list.positionViewAtIndex(i, ListView.Contain);
                });
            }
            delegate: Item {
                id: rowItem
                required property int index
                required property string rid
                required property string kind
                required property string type
                required property string title
                required property string subtitle
                required property string icon
                required property string sym
                readonly property bool isHeader: kind === "header"
                readonly property bool selected: rid === searchWindow.selectedId
                readonly property string contentScheme: selected ? "dark" : panel.scheme
                width: list.width
                height: isHeader ? searchWindow.headerH : searchWindow.rowH

                KText {
                    visible: rowItem.isHeader
                    x: 10
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 4
                    text: rowItem.title
                    textStyle: "sectionHeader"
                    level: "secondaryLabel"
                    scheme: panel.scheme
                }
                Rectangle {
                    visible: !rowItem.isHeader
                    anchors.fill: parent
                    radius: Theme.radius.listRow
                    color: rowItem.selected ? Theme.accentFor(panel.scheme) : (hover.hovered ? Theme.color(panel.scheme, "hover") : "transparent")
                }
                AppIcon {
                    visible: !rowItem.isHeader && rowItem.icon !== ""
                    x: 6
                    anchors.verticalCenter: parent.verticalCenter
                    size: 30
                    plain: rowItem.type === "file"
                    scheme: panel.scheme
                    source: visible ? rowItem.icon : ""
                }
                KIcon {
                    visible: !rowItem.isHeader && rowItem.icon === "" && rowItem.sym !== ""
                    x: 12
                    anchors.verticalCenter: parent.verticalCenter
                    size: 18
                    name: visible ? rowItem.sym : ""
                    color: rowItem.selected ? "#FFFFFF" : Theme.accentFor(panel.scheme)
                }
                KText {
                    visible: !rowItem.isHeader
                    x: 44
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.min(implicitWidth, parent.width - x - sub.implicitWidth - 24)
                    text: rowItem.title
                    textStyle: "body"
                    elide: Text.ElideRight
                    scheme: rowItem.contentScheme
                }
                KText {
                    id: sub
                    visible: !rowItem.isHeader
                    anchors.right: parent.right
                    anchors.rightMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.min(implicitWidth, parent.width * 0.45)
                    horizontalAlignment: Text.AlignRight
                    text: rowItem.subtitle
                    textStyle: "callout"
                    level: "secondaryLabel"
                    elide: Text.ElideMiddle
                    scheme: rowItem.contentScheme
                }
                HoverHandler { id: hover; enabled: !rowItem.isHeader }
                TapHandler {
                    enabled: !rowItem.isHeader
                    onTapped: searchWindow.activate(searchWindow.rows[rowItem.index], false)
                }
            }
        }
    }
}
