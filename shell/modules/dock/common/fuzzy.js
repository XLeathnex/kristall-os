// SPDX-License-Identifier: GPL-3.0-or-later
// Forgiving text matching for app names and settings pages (German and English): accent and
// umlaut folding, word prefixes, acronyms, substrings, subsequences and small typos.
// Pure functions, no allocation-heavy work per keystroke: callers pre-normalise their entries
// with prepare() once and call score() per query.
.pragma library

// "Lautstärke" → "lautstarke", "Lautstaerke" → "lautstarke", "Straße" → "strasse"
function norm(s) {
    if (!s)
        return "";
    s = String(s).toLowerCase();
    s = s.replace(/ä/g, "a").replace(/ö/g, "o").replace(/ü/g, "u").replace(/ß/g, "ss")
         .replace(/[àáâãå]/g, "a").replace(/[èéêë]/g, "e").replace(/[ìíîï]/g, "i")
         .replace(/[òóôõø]/g, "o").replace(/[ùúû]/g, "u").replace(/ç/g, "c").replace(/ñ/g, "n");
    s = s.replace(/ae/g, "a").replace(/oe/g, "o").replace(/ue/g, "u");
    return s.replace(/[^a-z0-9+#]+/g, " ").trim();
}

function words(n) {
    return n === "" ? [] : n.split(" ");
}

// one field: {n: normalised text, w: words, i: initials, c: compact (no spaces)}
function prepareField(text) {
    const n = norm(text);
    // split camel case and dotted ids too ("VisualStudioCode", "org.kde.dolphin")
    const raw = String(text || "").replace(/([a-z])([A-Z])/g, "$1 $2");
    const w = words(norm(raw));
    let i = "";
    for (const x of w)
        i += x.charAt(0);
    return { n: n, w: w, i: i, c: n.replace(/ /g, "") };
}

// fields: [{text, weight}] → prepared entry
function prepare(fields) {
    const out = [];
    const seen = {};
    for (const f of fields) {
        if (!f || !f.text)
            continue;
        const p = prepareField(f.text);
        if (p.n === "" || seen[p.n])
            continue;
        seen[p.n] = true;
        p.weight = f.weight === undefined ? 1 : f.weight;
        out.push(p);
    }
    return out;
}

// optimal string alignment distance between `q` and the best prefix of `w` (prefixes of length
// |q|±max), early exit above `max`. Reuses its rows: no allocation per call.
const _r0 = new Int32Array(64), _r1 = new Int32Array(64), _r2 = new Int32Array(64);
function prefixDistance(q, w, max) {
    const lq = q.length, lw = Math.min(w.length, lq + max, 63);
    if (lq > 60 || lw < lq - max)
        return max + 1;
    let p2 = _r2, p1 = _r0, cur = _r1;
    for (let j = 0; j <= lw; ++j)
        p1[j] = j;
    for (let i = 1; i <= lq; ++i) {
        cur[0] = i;
        let rowMin = i;
        const qc = q.charCodeAt(i - 1);
        for (let j = 1; j <= lw; ++j) {
            const wc = w.charCodeAt(j - 1);
            let v = p1[j - 1] + (qc === wc ? 0 : 1);
            if (p1[j] + 1 < v)
                v = p1[j] + 1;
            if (cur[j - 1] + 1 < v)
                v = cur[j - 1] + 1;
            if (i > 1 && j > 1 && qc === w.charCodeAt(j - 2) && q.charCodeAt(i - 2) === wc && p2[j - 2] + 1 < v)
                v = p2[j - 2] + 1;
            cur[j] = v;
            if (v < rowMin)
                rowMin = v;
        }
        if (rowMin > max)
            return max + 1;
        const t = p2;
        p2 = p1;
        p1 = cur;
        cur = t;
    }
    let best = max + 1;
    for (let j = Math.max(0, lq - max); j <= lw; ++j)
        if (p1[j] < best)
            best = p1[j];
    return best;
}

function distance(a, b, max) {
    return prefixDistance(a, b, max);
}

function allowedTypos(len) {
    return len >= 7 ? 2 : len >= 4 ? 1 : 0;
}

// is `q` a subsequence of `s`? returns the number of gaps, or -1
function subsequence(q, s) {
    let j = 0, gaps = 0, last = -1;
    for (let i = 0; i < s.length && j < q.length; ++i) {
        if (s.charCodeAt(i) === q.charCodeAt(j)) {
            if (last >= 0 && i !== last + 1)
                gaps++;
            last = i;
            j++;
        }
    }
    return j === q.length ? gaps : -1;
}

// score of one prepared field for a normalised query (0 = no match)
function scoreField(f, q, qw, cq) {
    if (f.n === q)
        return 1000;
    if (f.n.startsWith(q))
        return 900 - Math.min(80, f.n.length - q.length);
    // every query word starts a word of the field (in order or not)
    if (qw.length > 1) {
        let all = true;
        for (const x of qw) {
            let hit = false;
            for (const w of f.w)
                if (w.startsWith(x)) {
                    hit = true;
                    break;
                }
            if (!hit) {
                all = false;
                break;
            }
        }
        if (all)
            return 820;
    }
    for (let k = 1; k < f.w.length; ++k)
        if (f.w[k].startsWith(q))
            return 800 - k;
    if (cq.length >= 2 && f.i.length >= 2 && f.i.startsWith(cq))
        return 720;
    const at = f.c.indexOf(cq);
    if (cq.length >= 3 && at > 0)
        return 600 - Math.min(50, at);
    // typos against word prefixes of about the query's length (people rarely mistype the first
    // letter: only words that start with it are compared, which keeps this cheap)
    const typos = allowedTypos(cq.length);
    if (typos > 0) {
        let best = typos + 1;
        const c0 = cq.charCodeAt(0);
        for (const w of f.w) {
            if (w.charCodeAt(0) !== c0 || w.length < cq.length - typos)
                continue;
            const d = prefixDistance(cq, w, typos);
            if (d < best)
                best = d;
            if (best <= 1)
                break;
        }
        if (best <= typos)
            return 480 - 90 * best;
    }
    if (cq.length >= 3 && f.weight >= 0.9) {
        const gaps = subsequence(cq, f.c);
        if (gaps >= 0 && gaps <= 2)
            return 300 - 30 * gaps;
    }
    return 0;
}

// best weighted score over an entry's prepared fields
function score(entry, q, qw) {
    let best = 0;
    const cq = q.indexOf(" ") >= 0 ? q.replace(/ /g, "") : q;
    for (let i = 0; i < entry.length; ++i) {
        const f = entry[i];
        if (f.weight * 1000 <= best)
            continue;                   // cannot beat what we have
        const s = scoreField(f, q, qw, cq) * f.weight;
        if (s > best)
            best = s;
    }
    return best;
}

function query(text) {
    const q = norm(text);
    return { q: q, w: words(q) };
}
