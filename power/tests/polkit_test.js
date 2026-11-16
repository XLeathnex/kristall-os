// SPDX-License-Identifier: GPL-3.0-or-later
// Evaluates power/polkit/50-kristall-power.rules with a mock polkit object.
"use strict";
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
let rule = null;
const polkit = {
  Result: { YES: "yes", NO: "no", NOT_HANDLED: null, AUTH_ADMIN_KEEP: "auth_admin_keep" },
  addRule: (f) => { rule = f; },
};
new Function("polkit", src)(polkit);
const act = (unit, verb, id) => ({ id: id || "org.freedesktop.systemd1.manage-units", lookup: (k) => (k === "unit" ? unit : verb) });
const local = { local: true, active: true };
const cases = [
  ["kristall-power-charge@80.service", "start", local, "yes"],
  ["kristall-power-charge@50.service", "start", local, "yes"],
  ["kristall-power-charge@100.service", "start", local, "yes"],
  ["kristall-power-doctor.service", "start", local, "yes"],
  ["kristall-power-charge@49.service", "start", local, null],
  ["kristall-power-charge@101.service", "start", local, null],
  ["kristall-power-charge@8x.service", "start", local, null],
  ["kristall-power-charge@80.service", "stop", local, null],
  ["kristall-power.service", "start", local, null],
  ["kristall-power-charge@80.service", "start", { local: false, active: true }, null],
  ["kristall-power-charge@80.service", "start", { local: true, active: false }, null],
];
let fail = 0;
for (const [unit, verb, subj, want] of cases) {
  const got = rule(act(unit, verb), subj);
  const ok = got === want;
  if (!ok) fail++;
  console.log(`${ok ? "ok  " : "FAIL"} polkit ${verb} ${unit} local=${subj.local} active=${subj.active} -> ${got}`);
}
if (rule(act("x", "start", "org.freedesktop.login1.reboot"), local) !== null) { fail++; console.log("FAIL other actions not handled"); }
process.exit(fail ? 1 : 0);
