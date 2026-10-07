#!/usr/bin/env node
/* Build-time gate for the Order Source report.
 *
 * Usage: node tools/validate_order_source.js path/to/order-source.html [expected-lead-label]
 *
 * 1. Extracts every inline <script> and syntax-checks it (a template-literal slip
 *    makes the WHOLE script fail to parse, which leaves a blank report while every
 *    data check still passes).
 * 2. Runs the page in jsdom, collects script errors, then asserts the dynamic
 *    sections actually received content, for every period tab.
 * 3. Clicks the first expandable row to check the campaign drilldown.
 *
 * Exits non-zero on any failure so the workflow stops BEFORE publishing.
 * Requires the `jsdom` npm package (the workflow installs it with --no-save).
 */
"use strict";
const fs = require("fs");
const vm = require("vm");

const file = process.argv[2];
const expectLead = process.argv[3] || null;
if (!file) { console.error("usage: validate_order_source.js REPORT.html [Today|Yesterday]"); process.exit(2); }

const html = fs.readFileSync(file, "utf8");
const fails = [];
const fail = (m) => { fails.push(m); };

/* ---- 1. syntax check of every inline script -------------------------------- */
const scriptRe = /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi;
let m, nScripts = 0;
while ((m = scriptRe.exec(html))) {
  nScripts++;
  const before = html.slice(0, m.index + m[0].indexOf(">") + 1);
  const startLine = before.split("\n").length;
  try {
    new vm.Script(m[1], { filename: file + "#script" + nScripts });
  } catch (e) {
    const lm = /#script\d+:(\d+)/.exec(e.stack || "");
    const line = lm ? +lm[1] : 0;
    const src = (m[1].split("\n")[line - 1] || "").slice(0, 200);
    fail(`script ${nScripts} does not parse: ${e.message} (script line ${line}, html line ${startLine + line - 1}) -> ${src}`);
  }
}
if (!nScripts) fail("no inline <script> found");
if (/__[A-Z0-9_]+__/.test(html.replace(/<style[\s\S]*?<\/style>/g, ""))) {
  const left = html.match(/__[A-Z0-9_]+__/g);
  fail("unreplaced template placeholder(s): " + [...new Set(left)].join(", "));
}
if (/\(partial\)/i.test(html)) fail('report still contains "(partial)"');

if (fails.length) { report(); }

/* ---- 2. run the page --------------------------------------------------------- */
let JSDOM, VirtualConsole;
try { ({ JSDOM, VirtualConsole } = require("jsdom")); }
catch (e) { console.error("jsdom is not installed (npm install --no-save jsdom)"); process.exit(2); }

const errors = [];
const vc = new VirtualConsole();
vc.on("jsdomError", (e) => errors.push((e.detail && e.detail.message) || e.message));
vc.on("error", (e) => errors.push(String(e)));
const stages = [];
const dom = new JSDOM(html, {
  runScripts: "dangerously",
  pretendToBeVisual: true,
  virtualConsole: vc,
  url: "https://report.invalid/",
  beforeParse(win) {
    /* The report posts progress to its parent; emulate a parent frame. */
    Object.defineProperty(win, "parent", { value: { postMessage: (d) => {
      if (d && d.type === "report-render-error") errors.push("report-render-error: " + d.message + (d.line ? " (line " + d.line + ")" : ""));
      if (d && d.type === "report-render-stage") stages.push(d.stage);
    } } });
    win.requestAnimationFrame = (f) => setTimeout(f, 0);
  },
});
const doc = dom.window.document;

function check(label) {
  const q = (s) => doc.querySelector(s);
  const n = (s) => doc.querySelectorAll(s).length;
  if (!q("#flag").textContent.trim()) fail(`${label}: #flag is empty`);
  if (n("#profitKpis .profit-kpi") !== 4) fail(`${label}: #profitKpis should hold 4 tiles, has ${n("#profitKpis .profit-kpi")}`);
  if (n("#tabs button") !== 4) fail(`${label}: #tabs should hold 4 buttons, has ${n("#tabs button")}`);
  if (n("#rk tbody tr") < 2) fail(`${label}: #rk (profit ranking) has ${n("#rk tbody tr")} rows`);
  if (n("#rkt tbody tr") < 2) fail(`${label}: #rkt (rank by period) has ${n("#rkt tbody tr")} rows`);
  if (n("#etbl tbody tr") < 3) fail(`${label}: #etbl (spend/revenue/profit) has ${n("#etbl tbody tr")} rows`);
  if (n("#kpis .kpi") < 4) fail(`${label}: #kpis has ${n("#kpis .kpi")} cards`);
  if (n("#bars .bar") < 1) fail(`${label}: #bars has ${n("#bars .bar")} bars`);
  if (n("#tbl tbody tr") < 1) fail(`${label}: #tbl has ${n("#tbl tbody tr")} rows`);
  const bad = (doc.body.textContent.match(/NaN|undefined|\[object Object\]|Infinity/g) || []);
  if (bad.length) fail(`${label}: page text contains ${[...new Set(bad)].join(", ")}`);
}

setTimeout(() => {
  if (errors.length) errors.forEach((e) => fail("runtime error: " + e));
  if (!stages.includes("render-complete")) fail("render-complete was never reached");
  check("initial");

  const tabs = [...doc.querySelectorAll("#tabs button")];
  const lead = tabs[0] ? tabs[0].textContent.trim() : "";
  if (expectLead && lead !== expectLead) fail(`lead tab is "${lead}", expected "${expectLead}"`);
  const tile = doc.querySelector("#profitKpis .profit-kpi .l");
  if (tile && !/^(Today's|Yesterday's) Profit$/.test(tile.textContent.trim())) fail(`first profit tile label is "${tile.textContent.trim()}"`);

  /* every period tab must render every section */
  for (let i = 0; i < tabs.length; i++) {
    const btn = doc.querySelectorAll("#tabs button")[i];
    if (!btn) { fail(`tab ${i} vanished`); continue; }
    btn.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
    check("tab " + (btn.textContent.trim() || i));
  }

  /* campaign drilldown must expand */
  const before = doc.querySelectorAll("#etbl tbody tr").length;
  const tg = doc.querySelector("#etbl .tg");
  if (!tg) fail("#etbl has no expandable rows");
  else {
    tg.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
    const after = doc.querySelectorAll("#etbl tbody tr").length;
    if (after <= before) fail(`expanding a group did not add rows (${before} -> ${after})`);
  }
  if (errors.length > fails.filter((f) => f.startsWith("runtime error")).length) {
    errors.forEach((e) => { const t = "runtime error: " + e; if (!fails.includes(t)) fail(t); });
  }
  report();
}, 50);

function report() {
  if (fails.length) {
    console.error("ORDER SOURCE REPORT VALIDATION FAILED (" + fails.length + "):");
    fails.forEach((f) => console.error(" - " + f));
    process.exit(1);
  }
  const d = (s) => doc.querySelectorAll(s).length;
  console.log(`order-source render OK: ${nScripts} script(s) parse, tiles=${d("#profitKpis .profit-kpi")} tabs=${d("#tabs button")} rank=${d("#rk tbody tr")} byPeriod=${d("#rkt tbody tr")} etbl=${d("#etbl tbody tr")} kpis=${d("#kpis .kpi")} bars=${d("#bars .bar")} table=${d("#tbl tbody tr")}`);
  process.exit(0);
}
