// SPDX-License-Identifier: GPL-3.0-or-later
// Local calculator and unit conversion for Search (no eval, no network).
//   evaluate("3,5 * (2 + 1)") → 10.5    evaluate("sqrt 2 ^ 2") → 2    evaluate("15%") → 0.15
//   convert("5 km in mi") → {value, from, to, unit}    convert("100 °F") → default target
.pragma library

const FUNCS = {
    sqrt: Math.sqrt, "√": Math.sqrt, sin: x => Math.sin(x), cos: x => Math.cos(x), tan: x => Math.tan(x),
    asin: Math.asin, acos: Math.acos, atan: Math.atan, ln: Math.log, log: Math.log10, lg: Math.log10,
    abs: Math.abs, round: Math.round, floor: Math.floor, ceil: Math.ceil, exp: Math.exp
};
const CONSTS = { pi: Math.PI, "π": Math.PI, e: Math.E };

function tokenize(s) {
    const out = [];
    let i = 0;
    s = s.replace(/×/g, "*").replace(/÷/g, "/").replace(/−/g, "-").replace(/\*\*/g, "^");
    while (i < s.length) {
        const c = s[i];
        if (c === " ") {
            i++;
            continue;
        }
        const num = s.substring(i).match(/^(\d+(?:[.,]\d+)?|[.,]\d+)(?:e[+-]?\d+)?/i);
        if (num) {
            out.push({ t: "n", v: parseFloat(num[0].replace(",", ".")) });
            i += num[0].length;
            continue;
        }
        const word = s.substring(i).match(/^(sqrt|asin|acos|atan|sin|cos|tan|ln|log|lg|abs|round|floor|ceil|exp|pi|π|√|e)/i);
        if (word) {
            const w = word[0].toLowerCase();
            out.push(FUNCS[w] && w !== "e" ? { t: "f", v: w } : { t: "n", v: CONSTS[w] });
            i += word[0].length;
            continue;
        }
        if ("+-*/^%()".indexOf(c) >= 0) {
            out.push({ t: "o", v: c });
            i++;
            continue;
        }
        return null;
    }
    return out;
}

// recursive descent: expr = term (('+'|'-') term)* ; term = unary (('*'|'/') unary)* (implicit *)
// unary = '-' unary | power ; power = postfix ('^' unary)? ; postfix = primary '%'?
function parse(tokens) {
    let p = 0;
    const peek = () => tokens[p];
    const isOp = (v) => peek() && peek().t === "o" && peek().v === v;
    function primary() {
        const tk = peek();
        if (!tk)
            throw "end";
        if (tk.t === "n") {
            p++;
            return tk.v;
        }
        if (tk.t === "f") {
            p++;
            const arg = isOp("(") ? primary() : unary();
            return FUNCS[tk.v](arg);
        }
        if (isOp("(")) {
            p++;
            const v = expr();
            if (!isOp(")"))
                throw "paren";
            p++;
            return v;
        }
        throw "unexpected";
    }
    function postfix() {
        let v = primary();
        while (isOp("%")) {
            p++;
            v = v / 100;
        }
        return v;
    }
    function power() {
        const b = postfix();
        if (isOp("^")) {
            p++;
            return Math.pow(b, unary());
        }
        return b;
    }
    function unary() {
        if (isOp("-")) {
            p++;
            return -unary();
        }
        if (isOp("+")) {
            p++;
            return unary();
        }
        return power();
    }
    function term() {
        let v = unary();
        for (;;) {
            if (isOp("*") || isOp("/")) {
                const op = peek().v;
                p++;
                const r = unary();
                v = op === "*" ? v * r : v / r;
            } else if (peek() && (peek().t === "n" || peek().t === "f" || isOp("("))) {
                v = v * unary();          // implicit multiplication: 2pi, 3(4+1)
            } else {
                return v;
            }
        }
    }
    function expr() {
        let v = term();
        while (isOp("+") || isOp("-")) {
            const op = peek().v;
            p++;
            const r = term();
            v = op === "+" ? v + r : v - r;
        }
        return v;
    }
    const v = expr();
    if (p !== tokens.length)
        throw "trailing";
    return v;
}

// a number, or null when `text` is not a calculation (plain numbers are not)
function evaluate(text) {
    const s = String(text || "").trim().replace(/=$/, "").trim();
    if (s === "" || !/\d|pi|π/i.test(s) || !/[-+*/^%×÷()√]|sqrt|sin|cos|tan|ln|log|abs/i.test(s.replace(/^-/, "")))
        return null;
    const tokens = tokenize(s);
    if (!tokens || tokens.length < 2)
        return null;
    try {
        const v = parse(tokens);
        return isFinite(v) ? v : null;
    } catch (e) {
        return null;
    }
}

// ---- units ------------------------------------------------------------------------------------
// [dimension, factor to the base unit, display symbol, names…]
const UNITS = [
    ["length", 1, "m", "m", "meter", "metre", "meters", "metres"],
    ["length", 1000, "km", "km", "kilometer", "kilometre", "kilometers", "kilometres"],
    ["length", 0.01, "cm", "cm", "zentimeter", "centimeter", "centimetre"],
    ["length", 0.001, "mm", "mm", "millimeter", "millimetre"],
    ["length", 0.0254, "in", "in", "inch", "inches", "zoll", "\""],
    ["length", 0.3048, "ft", "ft", "foot", "feet", "fuß", "fuss"],
    ["length", 0.9144, "yd", "yd", "yard", "yards"],
    ["length", 1609.344, "mi", "mi", "mile", "miles", "meile", "meilen"],
    ["mass", 1, "kg", "kg", "kilogram", "kilogramm", "kilo"],
    ["mass", 0.001, "g", "g", "gram", "gramm", "grams"],
    ["mass", 1000, "t", "t", "tonne", "tonnen", "ton"],
    ["mass", 0.45359237, "lb", "lb", "lbs", "pound", "pounds", "pfund"],
    ["mass", 0.028349523125, "oz", "oz", "ounce", "ounces", "unze", "unzen"],
    ["volume", 1, "l", "l", "liter", "litre", "liters", "litres"],
    ["volume", 0.001, "ml", "ml", "milliliter", "millilitre"],
    ["volume", 3.785411784, "gal", "gal", "gallon", "gallons", "gallone", "gallonen"],
    ["volume", 0.2365882365, "cup", "cup", "cups", "tasse", "tassen"],
    ["volume", 0.0295735295625, "fl oz", "floz", "fl oz", "fluid ounce"],
    ["speed", 1, "km/h", "km/h", "kmh", "kph"],
    ["speed", 1.609344, "mph", "mph"],
    ["speed", 3.6, "m/s", "m/s", "mps"],
    ["speed", 1.852, "kn", "kn", "knot", "knots", "knoten"],
    ["data", 1, "B", "b", "byte", "bytes"],
    ["data", 1e3, "KB", "kb", "kilobyte"],
    ["data", 1e6, "MB", "mb", "megabyte"],
    ["data", 1e9, "GB", "gb", "gigabyte"],
    ["data", 1e12, "TB", "tb", "terabyte"],
    ["data", 1024, "KiB", "kib"],
    ["data", 1048576, "MiB", "mib"],
    ["data", 1073741824, "GiB", "gib"],
    ["time", 1, "s", "s", "sec", "second", "seconds", "sekunde", "sekunden"],
    ["time", 60, "min", "min", "minute", "minutes", "minuten"],
    ["time", 3600, "h", "h", "hour", "hours", "stunde", "stunden", "std"],
    ["time", 86400, "d", "d", "day", "days", "tag", "tage"],
    ["temp", 0, "°C", "°c", "c", "celsius", "grad"],
    ["temp", 0, "°F", "°f", "f", "fahrenheit"],
    ["temp", 0, "K", "k", "kelvin"]
];
const DEFAULT_TARGET = { km: "mi", mi: "km", m: "ft", ft: "m", cm: "in", in: "cm", mm: "in", yd: "m", kg: "lb", lb: "kg", g: "oz",
                         oz: "g", t: "lb", l: "gal", gal: "l", ml: "fl oz", cup: "ml", "fl oz": "ml", "km/h": "mph", mph: "km/h",
                         "m/s": "km/h", kn: "km/h", "°C": "°F", "°F": "°C", K: "°C", B: "KB", KB: "KiB", MB: "MiB", GB: "GiB",
                         TB: "GiB", KiB: "KB", MiB: "MB", GiB: "GB", s: "min", min: "h", h: "min", d: "h" };

function unit(name) {
    const n = String(name || "").toLowerCase().trim().replace(/^grad\s+/, "°").replace(/^°\s+/, "°");
    if (n === "")
        return null;
    for (const u of UNITS)
        for (let i = 3; i < u.length; ++i)
            if (u[i] === n)
                return { dim: u[0], f: u[1], sym: u[2] };
    return null;
}
function bySym(sym) {
    for (const u of UNITS)
        if (u[2] === sym)
            return { dim: u[0], f: u[1], sym: u[2] };
    return null;
}
function toKelvin(v, sym) {
    return sym === "°C" ? v + 273.15 : sym === "°F" ? (v - 32) * 5 / 9 + 273.15 : v;
}
function fromKelvin(k, sym) {
    return sym === "°C" ? k - 273.15 : sym === "°F" ? (k - 273.15) * 9 / 5 + 32 : k;
}

// "5 km in mi", "5km to miles", "100 °F", "3 Fuß nach m" → {value, amount, from, to} or null
function convert(text) {
    const m = String(text || "").trim().match(/^(-?\d+(?:[.,]\d+)?)\s*([^\d\s][^]*?)(?:\s+(?:in|to|into|zu|nach|als|=|->|→)\s+(.+))?\s*$/i);
    if (!m)
        return null;
    const amount = parseFloat(m[1].replace(",", "."));
    const from = unit(m[2]);
    if (!from)
        return null;
    let to = m[3] ? unit(m[3]) : bySym(DEFAULT_TARGET[from.sym]);
    if (!to || to.dim !== from.dim || to.sym === from.sym)
        return null;
    let value;
    if (from.dim === "temp")
        value = fromKelvin(toKelvin(amount, from.sym), to.sym);
    else
        value = amount * from.f / to.f;
    return { value: value, amount: amount, from: from.sym, to: to.sym };
}

// display: up to 10 significant digits, the system language's decimal mark
function format(v, lang) {
    let s;
    if (Math.abs(v) >= 1e15 || (Math.abs(v) < 1e-6 && v !== 0))
        s = v.toExponential(6).replace(/\.?0+e/, "e");
    else
        s = String(parseFloat(v.toPrecision(10)));
    if (lang === "de")
        s = s.replace(".", ",");
    return s;
}
