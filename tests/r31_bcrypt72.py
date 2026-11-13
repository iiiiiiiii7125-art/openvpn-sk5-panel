#!/usr/bin/env python3
"""AUDIT-R31 bcrypt-72 probe (auditor-written, expectations flipped by
the R31-P2-2 fix lane — BH-03(c) style: the auditor's original probe
pinned the DEFECT (73+/74-byte new passwords -> unhandled 500); this
version asserts the FIXED behavior (400 naming the 72-byte limit, old
password still valid). bcrypt 5.x hashpw raises ValueError past 72
bytes; _validate_new_password now caps UTF-8 at 72 bytes and
change_password keeps a ValueError guard as defense in depth.
R33-P2-1 extension (F1-F4, added by the R33 fix lane): the 72-byte cap
was server-only; the frontend validation and all user-facing rule
enumerations still promised the old three rules. F1-F3 are BEHAVIORAL:
they extract the REAL change-password validation block from
panel/templates/index.html and run it in Node against the same
passwords (the block's own `return;` exits are honored — the stubbed
showMsg captures the message before the return). F4 is a CONTENT PIN:
each of the six user-facing rule enumerations must name the 72-byte
limit (docs/security.md, index.html help text + comment, panel/README
API row + bullet, README.md).
Run as nobody with PYTHONPATH=venv site-packages (fresh data dir).
Exit code = number of FAILs.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

TREE = Path(os.environ.get("R31_TREE", "/tmp/r31/ptree"))
sys.path.insert(0, str(TREE / "panel"))
sys.path.insert(0, str(TREE / "core"))
sys.path.insert(0, str(TREE / "egress"))

import app as panel  # noqa: E402

RESULTS = []


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (" | " + detail if detail else ""))


def frontend_validate(passwords):
    """Run the REAL frontend change-password validation block (extracted
    verbatim from panel/templates/index.html) in Node. Returns a dict
    name -> message (None = passed all checks) or raises on harness
    failure (extraction fail / node error) so the cells FAIL loudly."""
    html = (TREE / "panel" / "templates" / "index.html").read_text()
    start = html.index("if (newPw !== confirmPw)")
    end = html.index("  try {", start)
    block = html[start:end]
    js = (
        'const fs = require("fs");\n'
        '// node -e: process.argv has NO script element — argv[1] is the\n'
        '// first argument after the eval string (html path), argv[2] the\n'
        '// JSON cases.\n'
        'const html = fs.readFileSync(process.argv[1], "utf8");\n'
        'const start = html.indexOf("if (newPw !== confirmPw)");\n'
        'const end = html.indexOf("  try {", start);\n'
        'if (start < 0 || end < 0) { console.log("EXTRACT_FAIL"); process.exit(2); }\n'
        'const block = html.slice(start, end);\n'
        'const fn = new Function("newPw", "oldPw", "confirmPw", "out",\n'
        '  "function showMsg(id, text, ok) { out.msg = text; }\\n" + block);\n'
        'const cases = JSON.parse(process.argv[2]);\n'
        'for (const c of cases) {\n'
        '  const out = {msg: null};\n'
        '  fn(c.newPw, c.oldPw, c.confirmPw, out);\n'
        '  console.log(JSON.stringify({name: c.name, msg: out.msg}));\n'
        '}\n'
    )
    cases = [
        {"name": name, "newPw": pw, "oldPw": "OldPass123456", "confirmPw": pw}
        for name, pw in passwords
    ]
    r = subprocess.run(
        ["node", "-e", js, str(TREE / "panel" / "templates" / "index.html"),
         json.dumps(cases, ensure_ascii=False)],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        raise RuntimeError(f"node harness failed rc={r.returncode}: {r.stderr.strip()}")
    out = {}
    for line in r.stdout.splitlines():
        d = json.loads(line)
        out[d["name"]] = d["msg"]
    if set(out) != {name for name, _ in passwords}:
        raise RuntimeError(f"node harness incomplete output: {r.stdout!r}")
    return out


def main():
    pw = panel._ensure_admin_password()
    assert pw, "admin password not generated"
    c = panel.app.test_client()
    ip = "10.9.0.2"

    def login(password):
        r = c.post("/api/login", json={"password": password},
                   environ_base={"REMOTE_ADDR": ip})
        return r.status_code

    def change(old, new):
        r = c.post("/api/change-password",
                   json={"old_password": old, "new_password": new},
                   environ_base={"REMOTE_ADDR": ip})
        return r.status_code, (r.get_json() or {})

    assert login(pw) == 200
    # B1: 72 bytes exactly (70 a's + '12') -> must succeed.
    s, j = change(pw, "a" * 70 + "12")
    print(f"B1 72-byte new password: {s} {j}")
    cell("B1 72-byte new password -> 200", s == 200)
    pw2 = "a" * 70 + "12"
    assert login(pw2) == 200, "72-byte password must log in afterwards"
    # B2: 73 bytes (71 a's + '12') -> fixed: 400 naming the 72-byte limit.
    s, j = change(pw2, "a" * 71 + "12")
    print(f"B2 73-byte new password: {s} {j}")
    cell("B2 73-byte new password -> 400 naming 72-byte limit",
         s == 400 and "72" in (j.get("error") or ""))
    # old password must still work after the rejected change.
    s2 = login(pw2)
    print(f"B2b old password still logs in: {s2}")
    cell("B2b old password still valid after 400", s2 == 200)
    # B3: multibyte — 1 ascii + 24 CJK (72 bytes) + 1 digit = 74 bytes.
    s, j = change(pw2, "a" + "密" * 24 + "1")
    print(f"B3 74-byte multibyte new password: {s} {j}")
    cell("B3 74-byte multibyte new password -> 400 naming 72-byte limit",
         s == 400 and "72" in (j.get("error") or ""))
    s2 = login(pw2)
    cell("B3b old password still valid after 400", s2 == 200)
    # B4: 72 bytes multibyte — 1 ascii + 23 CJK (69 bytes) + 2 digits = 72 bytes.
    s, j = change(pw2, "a" + "密" * 23 + "12")
    print(f"B4 72-byte multibyte new password: {s} {j}")
    cell("B4 72-byte multibyte new password -> 200", s == 200)

    # R33-P2-1: frontend validation must pre-intercept the same
    # passwords the server rejects (F1-F3 behavioral — real handler
    # block extracted from index.html, run in Node).
    try:
        msgs = frontend_validate([
            ("f1-74byte", "a" + "密" * 24 + "1"),   # 26 chars, 74 bytes
            ("f2-72byte", "a" + "密" * 23 + "12"),  # 26 chars, 72 bytes
            ("f3-73byte", "a" * 71 + "12"),         # 73 bytes ASCII
        ])
    except Exception as e:  # harness failure must FAIL loudly, never pass
        print(f"frontend harness error: {e}")
        msgs = {}
    print(f"F frontend messages: {msgs}")
    # NOTE: each cell requires its case key to be PRESENT in msgs —
    # a harness failure leaves msgs empty, which must FAIL (never
    # pass vacuously, e.g. F2's None on a missing key).
    cell("F1 frontend rejects 74-byte multibyte with 72-byte message",
         "f1-74byte" in msgs and msgs["f1-74byte"] is not None
         and "72" in msgs["f1-74byte"],
         msgs.get("f1-74byte") or "no message")
    cell("F2 frontend accepts 72-byte multibyte (passes all checks)",
         "f2-72byte" in msgs and msgs["f2-72byte"] is None,
         repr(msgs.get("f2-72byte")))
    cell("F3 frontend rejects 73-byte ASCII with 72-byte message",
         "f3-73byte" in msgs and msgs["f3-73byte"] is not None
         and "72" in msgs["f3-73byte"],
         msgs.get("f3-73byte") or "no message")

    # F4: content pin — every user-facing rule enumeration must name
    # the 72-byte limit (R33-P2-1: the six locations).
    pins = [
        ("docs/security.md 改密 row", TREE / "docs" / "security.md", "改密"),
        ("index.html help text", TREE / "panel" / "templates" / "index.html",
         "新密码至少 12 个字符"),
        ("index.html validation comment", TREE / "panel" / "templates" / "index.html",
         "强度校验（≥12 字符"),
        ("panel/README.md API row", TREE / "panel" / "README.md",
         "POST `/api/change-password`"),
        ("panel/README.md 改密 bullet", TREE / "panel" / "README.md",
         "前端先校验新密码强度"),
        ("README.md 改密 bullet", TREE / "README.md", "改密接口"),
    ]
    missing = []
    for name, path, marker in pins:
        lines = [ln for ln in path.read_text().splitlines() if marker in ln]
        if not lines or not any("72" in ln for ln in lines):
            missing.append(name)
    cell("F4 all six user-facing rule enumerations name the 72-byte limit",
         not missing, ("missing: " + ", ".join(missing)) if missing else "")

    fails = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"R31 bcrypt-72 (flask): {len(RESULTS) - fails}/{len(RESULTS)}")
    sys.exit(fails)


if __name__ == "__main__":
    main()
