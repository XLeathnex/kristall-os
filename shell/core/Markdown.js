// SPDX-License-Identifier: GPL-3.0-or-later
// A small, safe Markdown subset -> Qt rich text for the assistant's replies.
// Everything is HTML-escaped first; only tags generated here reach the TextEdit (no raw HTML, no
// images, links only for http/https/mailto). Supported: paragraphs, line breaks, headings (shown as
// bold lines), bullet and numbered lists (one nesting level), block quotes, fenced and indented
// code, horizontal rules, **bold**, *italic*/_italic_, `code`, ~~strike~~, [text](url).
// Unfinished markers at the end of a streaming reply are hidden so half-typed syntax never flickers.
.pragma library

function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function safeUrl(u) {
    const t = u.trim();
    if (/^(https?:\/\/|mailto:)/i.test(t))
        return t.replace(/"/g, "%22");
    return "";
}

// inline formatting of one escaped line; `o` carries colours/fonts
function inline(text, o, streaming) {
    // protect code spans first
    const codes = [];
    let s = text.replace(/`([^`]+)`/g, function (m, c) {
        codes.push(c);
        return "\u0000" + (codes.length - 1) + "\u0000";
    });
    s = esc(s);
    // links [text](url)
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (m, label, url) {
        const u = safeUrl(url.replace(/&amp;/g, "&"));
        if (!u)
            return label;
        return '<a href="' + esc(u) + '" style="color:' + o.link + ';text-decoration:none">' + label + "</a>";
    });
    s = s.replace(/\*\*([^*]+?)\*\*/g, "<b>$1</b>");
    s = s.replace(/__([^_]+?)__/g, "<b>$1</b>");
    s = s.replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?!\w)/g, "$1<i>$2</i>");
    s = s.replace(/(^|[^\w])_([^_\s][^_]*?)_(?!\w)/g, "$1<i>$2</i>");
    s = s.replace(/~~([^~]+?)~~/g, "<s>$1</s>");
    if (streaming) {
        // a marker still waiting for its partner at the very end: hide it for now
        s = s.replace(/(\*\*|\*|__|~~|`)$/, "");
        s = s.replace(/\[([^\]]*)$/, "$1");
        s = s.replace(/\]\([^)]*$/, "");
    }
    s = s.replace(/\u0000(\d+)\u0000/g, function (m, i) {
        return '<span style="font-family:' + o.mono + ';background-color:' + o.codeBg + '">&#8202;' + esc(codes[+i]) + "&#8202;</span>";
    });
    return s;
}

// text: markdown; o: {color, secondary, link, codeBg, mono, size, line, gap}; streaming: bool
function toHtml(text, o, streaming) {
    const lines = String(text || "").replace(/\r/g, "").split("\n");
    const out = [];
    const gap = o.gap !== undefined ? o.gap : 8;
    const pStyle = "margin-top:0;margin-bottom:" + gap + "px;line-height:" + (o.lineHeight || 135) + "%";
    let para = [];
    let list = null;           // {type:"ul"|"ol", items:[[text, level]]}
    let code = null;           // array of lines inside a fence
    let quote = [];

    function flushPara() {
        if (para.length) {
            out.push('<p style="' + pStyle + '">' + para.map(l => inline(l, o, streaming)).join("<br>") + "</p>");
            para = [];
        }
    }
    function flushList() {
        if (!list)
            return;
        let h = "<" + list.type + ' style="margin-top:0;margin-bottom:' + gap + 'px;margin-left:0;-qt-list-indent:1">';
        for (const it of list.items)
            h += '<li style="margin-bottom:3px;line-height:' + (o.lineHeight || 135) + '%' + (it[1] > 0 ? ";margin-left:18px" : "") + '">' + inline(it[0], o, streaming) + "</li>";
        out.push(h + "</" + list.type + ">");
        list = null;
    }
    function flushQuote() {
        if (quote.length) {
            out.push('<p style="' + pStyle + ';margin-left:10px;color:' + o.secondary + '">' + quote.map(l => inline(l, o, streaming)).join("<br>") + "</p>");
            quote = [];
        }
    }
    function flushAll() {
        flushPara();
        flushList();
        flushQuote();
    }

    for (let i = 0; i < lines.length; ++i) {
        const raw = lines[i];
        if (code !== null) {
            if (/^\s*(```|~~~)/.test(raw)) {
                out.push('<pre style="margin-top:0;margin-bottom:' + gap + 'px;font-family:' + o.mono + ';background-color:' + o.codeBg + '">' + esc(code.join("\n")) + "</pre>");
                code = null;
            } else {
                code.push(raw);
            }
            continue;
        }
        if (/^\s*(```|~~~)/.test(raw)) {
            flushAll();
            code = [];
            continue;
        }
        const line = raw.replace(/\s+$/, "");
        if (line.trim() === "") {
            flushAll();
            continue;
        }
        let m;
        if ((m = /^\s{0,3}(#{1,6})\s+(.*)$/.exec(line))) {
            flushAll();
            const big = m[1].length <= 2;
            out.push('<p style="margin-top:' + (out.length ? 4 : 0) + 'px;margin-bottom:' + Math.round(gap * 0.75) + 'px"><b' +
                     (big ? ' style="font-size:' + Math.round((o.size || 13) * 1.15) + 'px"' : "") + ">" + inline(m[2].replace(/\s+#+$/, ""), o, streaming) + "</b></p>");
            continue;
        }
        if (/^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(line)) {
            flushAll();
            out.push('<hr style="margin-top:2px;margin-bottom:' + gap + 'px">');
            continue;
        }
        if ((m = /^(\s*)([-*+•])\s+(.*)$/.exec(line))) {
            flushPara();
            flushQuote();
            if (!list || list.type !== "ul") {
                flushList();
                list = { type: "ul", items: [] };
            }
            list.items.push([m[3], m[1].length >= 2 ? 1 : 0]);
            continue;
        }
        if ((m = /^(\s*)(\d{1,3})[.)]\s+(.*)$/.exec(line))) {
            flushPara();
            flushQuote();
            if (!list || list.type !== "ol") {
                flushList();
                list = { type: "ol", items: [] };
            }
            list.items.push([m[3], m[1].length >= 2 ? 1 : 0]);
            continue;
        }
        if ((m = /^\s*>\s?(.*)$/.exec(line))) {
            flushPara();
            flushList();
            quote.push(m[1]);
            continue;
        }
        if (list && /^\s{2,}\S/.test(raw)) {      // continuation of a list item
            const last = list.items[list.items.length - 1];
            last[0] += " " + line.trim();
            continue;
        }
        flushList();
        flushQuote();
        para.push(line);
    }
    if (code !== null)
        out.push('<pre style="margin-top:0;margin-bottom:0;font-family:' + o.mono + ';background-color:' + o.codeBg + '">' + esc(code.join("\n")) + "</pre>");
    flushAll();
    // the last block carries no bottom margin
    if (out.length)
        out[out.length - 1] = out[out.length - 1].replace(/margin-bottom:\d+px/, "margin-bottom:0px");
    return out.join("");
}

// plain text for copying (markers removed)
function toPlain(text) {
    return String(text || "")
        .replace(/```[a-zA-Z]*\n?/g, "")
        .replace(/\*\*([^*]+)\*\*/g, "$1")
        .replace(/__([^_]+)__/g, "$1")
        .replace(/`([^`]+)`/g, "$1")
        .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1 ($2)")
        .replace(/^\s{0,3}#{1,6}\s+/gm, "")
        .trim();
}

// does the text use any block or inline markup (decides "short spoken-style" vs "formatted")
function hasMarkup(text) {
    return /(^|\n)\s*([-*+•]|\d+[.)]|#{1,6}|>|```)\s|\*\*|`|\[[^\]]+\]\(/.test(String(text || ""));
}
