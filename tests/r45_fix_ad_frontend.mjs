// R45-LIVE-2 agent-delivery probe -- frontend half (r45_fix_ad.py
// is the Flask half, r45_fix_ad_worker.mjs the Worker half).
// buildUpdateCommand (panel/templates/index.html) builds the agent
// code-update command: same verified-download shape as the install
// command, but WITHOUT --token (a re-run keeps the existing token)
// and WITH --force (otherwise P2-13 refuses to overwrite an existing
// install). The real function source is extracted from index.html and
// executed, not re-implemented here.
// Usage: node tests/r45_fix_ad_frontend.mjs (exit = FAIL count)
import { readFileSync } from "node:fs";

const html = readFileSync(
  new URL("../panel/templates/index.html", import.meta.url), "utf8");

const RESULTS = [];
function cell(name, cond, detail = "") {
  RESULTS.push([name, !!cond]);
  console.log((cond ? "PASS " : "FAIL ") + name + (detail ? " | " + detail : ""));
}

function extract(name) {
  const m = html.match(new RegExp(`function ${name}\\([^)]*\\) \\{[\\s\\S]*?\\n\\}`));
  return m ? m[0] : null;
}

const shellQuoteSrc = extract("shellQuote");
const updateSrc = extract("buildUpdateCommand");
const installSrc = extract("buildInstallCommand");
cell("F1 buildUpdateCommand exists in index.html", updateSrc !== null);
cell("F1b shellQuote exists in index.html", shellQuoteSrc !== null);
cell("F1c buildInstallCommand exists in index.html", installSrc !== null);

if (shellQuoteSrc && updateSrc && installSrc) {
  // new Function: the real sources execute (no re-implementation);
  // `location` is passed in as the browser global the code expects.
  const factory = new Function(
    "location",
    `${shellQuoteSrc}\n${updateSrc}\n${installSrc}\nreturn { buildUpdateCommand, buildInstallCommand };`,
  );
  const { buildUpdateCommand, buildInstallCommand } =
    factory({ origin: "https://panel.example:8443" });
  const cmd = buildUpdateCommand("https://panel.example:8443", "n1");
  cell("F2 update command carries --force", cmd.includes("--force"), cmd);
  cell("F3 update command omits --token", !cmd.includes("--token"), cmd);
  cell("F4 update command names panel URL + node",
    cmd.includes("https://panel.example:8443") && cmd.includes("--node-name 'n1'"), cmd);
  cell("F5 update command keeps script verification (sha256 step)",
    cmd.includes("install-agent.sh.sha256") && cmd.includes("sha256sum -c"), cmd);
  const icmd = buildInstallCommand("https://panel.example:8443", "tok-1", "n1");
  cell("F6 control: install command still carries --token, no --force",
    icmd.includes("--token 'tok-1'") && !icmd.includes("--force"), icmd);
}

const fails = RESULTS.filter(([, ok]) => !ok).length;
console.log("----");
console.log(`checks=${RESULTS.length} failures=${fails}`);
process.exit(fails ? 1 : 0);
