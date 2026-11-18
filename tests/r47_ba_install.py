#!/usr/bin/env python3
"""R47 Fix-BA probe: install/upgrade/uninstall fixes (R47-L1-1..L1-4, R47-L5-4).

Run as ROOT (the systemd cells need real units; the sandbox has
systemd 255 as PID 1). TREE override: R47BA_TREE (default: this
repo). Every defect cell FAILS on the 1.0.3 baseline by design and
PASSES on the fixed tree (BH-03(c): the flip asserts fixed behavior).

Cells:
  H1 core-only change    -> _panel_code_hash MUST change
  H2 egress-only change  -> MUST change
  H3 panel unit change   -> MUST change
  H4 panel change        -> MUST change (control)
  H5 agent-only change   -> MUST NOT change (control: panel reads agent/ per request)
  H6 no change           -> MUST NOT change (control)
  R1 DNS-only re-render  -> server.conf changes (real render_server_conf)
  R2 conf changed + unit active -> _restart_openvpn_if_conf_changed restarts it (PID changes)
  R3 conf unchanged      -> no restart (PID unchanged)
  R4 conf changed + unit inactive -> returns 0, unit stays inactive
  R5 port change refused -> render_server_conf raises (control: freeze stays loud)
  W1 stale NRestarts (1 historical auto-restart) -> wait_steady_active PASSES
  W2 genuine restart inside the settle window -> gate DIES and the message names reset-failed
  U1 uninstall-agent.sh removes fake roots + stops/disables the unit; second run is a clean no-op
  U2 README uninstall block: no literal <网卡>, real interface lookup, caddy disable conditional
     on the marker, /var/log/openvpn removed, agent uninstall invoked
  U3 agent/README.md has an uninstall section naming uninstall-agent.sh
  U4 install.sh writes the caddy-installed marker on the install path; README reads the same path
  U5 node-revoke confirm dialog names uninstall-agent.sh
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

TREE = os.environ.get("R47BA_TREE") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNIT = "r47ba-test.service"
UNIT_PATH = "/etc/systemd/system/%s" % UNIT
AGENT_UNIT = "ovpn-agent.service"
AGENT_UNIT_PATH = "/etc/systemd/system/%s" % AGENT_UNIT

RESULTS = []


def record(name, ok, detail=""):
    RESULTS.append((name, "PASS" if ok else "FAIL", detail))
    print("%-4s %-8s %s" % (name, "PASS" if ok else "FAIL", detail))


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)


def extract_fn(install_sh, name):
    text = open(install_sh, encoding="utf-8").read()
    start = text.index(name + "() {")
    end = text.index("\n}\n", start) + len("\n}\n")
    return text[start:end]


def write_unit(path, exec_start, restart="no"):
    with open(path, "w") as f:
        f.write("[Unit]\nDescription=r47ba probe dummy\n\n[Service]\n"
                "ExecStart=%s\nRestart=%s\nRestartSec=1\n\n[Install]\nWantedBy=multi-user.target\n"
                % (exec_start, restart))
    sh("systemctl daemon-reload")


def unit_pid(unit):
    out = sh("systemctl show %s -p MainPID --value" % unit).stdout.strip()
    return int(out) if out.isdigit() else 0


def unit_active(unit):
    return sh("systemctl is-active --quiet %s" % unit).returncode == 0


def wait_active(unit, timeout=10):
    for _ in range(int(timeout * 5)):
        if unit_active(unit) and unit_pid(unit) > 0:
            return True
        time.sleep(0.2)
    return False


def wait_nrestarts(unit, want, timeout=10):
    for _ in range(int(timeout * 5)):
        out = sh("systemctl show %s -p NRestarts --value" % unit).stdout.strip()
        if out == str(want):
            return True
        time.sleep(0.2)
    return False


def cleanup_units():
    for u, p in ((UNIT, UNIT_PATH), (AGENT_UNIT, AGENT_UNIT_PATH)):
        sh("systemctl stop %s 2>/dev/null; systemctl disable %s 2>/dev/null; rm -f %s; systemctl reset-failed %s 2>/dev/null"
           % (u, u, p, u))
    sh("systemctl daemon-reload")


# ---------------------------------------------------------------- H: hash matrix
def section_hash():
    install_sh = os.path.join(TREE, "install.sh")
    try:
        fn_src = extract_fn(install_sh, "_panel_code_hash")
    except ValueError:
        for n in ("H1", "H2", "H3", "H4", "H5", "H6"):
            record(n, False, "_panel_code_hash not found in install.sh")
        return
    tmp = tempfile.mkdtemp(prefix="r47ba-hash-")
    root = os.path.join(tmp, "install-root")
    os.makedirs(root)
    with open(os.path.join(root, "run-panel-tls.py"), "w") as f:
        f.write("# generated launcher stand-in\n")
    os.makedirs(os.path.join(root, "systemd"))
    with open(os.path.join(root, "systemd", "openvpn-sk5-panel.service"), "w") as f:
        f.write("[Unit]\nDescription=panel stand-in\n")
    for d in ("panel", "core", "egress", "agent"):
        shutil.copytree(os.path.join(TREE, d), os.path.join(root, d),
                        ignore=shutil.ignore_patterns("data", "__pycache__"))
    fn_path = os.path.join(tmp, "hash-fn.sh")
    with open(fn_path, "w") as f:
        f.write(fn_src)

    def run_hash():
        out = subprocess.run(["bash", "-c", "source %s; _panel_code_hash" % fn_path],
                             env={**os.environ, "INSTALL_ROOT": root},
                             capture_output=True, text=True)
        return out.stdout.strip(), out.returncode

    base, rc = run_hash()
    if rc != 0 or not base:
        for n in ("H1", "H2", "H3", "H4", "H5", "H6"):
            record(n, False, "_panel_code_hash failed to run (rc=%d)" % rc)
        shutil.rmtree(tmp, ignore_errors=True)
        return

    def cell(name, path, expect_change, edit=None):
        with open(path, encoding="utf-8") as f:
            orig = f.read()
        new = edit(orig) if edit else orig + "\n# R47BA-PROBE-MARKER\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(new)
        h, _ = run_hash()
        with open(path, "w", encoding="utf-8") as f:
            f.write(orig)
        changed = (h != base)
        record(name, changed == expect_change,
               "changed" if changed else "unchanged")

    core = os.path.join(root, "core", "openvpn_manager.py")
    cell("H1", core, True,
         edit=lambda c: c.replace("A-Za-z0-9_-]{1,32}", "A-Za-z0-9_.-]{1,32}", 1))
    cell("H2", os.path.join(root, "egress", "sk5_manager.py"), True)
    cell("H3", os.path.join(root, "systemd", "openvpn-sk5-panel.service"), True)
    cell("H4", os.path.join(root, "panel", "app.py"), True)
    cell("H5", os.path.join(root, "agent", "agent.py"), False)
    h2, _ = run_hash()
    record("H6", h2 == base, "stable" if h2 == base else "flapping")
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- R: render + restart
def section_render():
    sys.path.insert(0, os.path.join(TREE, "core"))
    from openvpn_manager import render_server_conf  # noqa: E402

    tmp = tempfile.mkdtemp(prefix="r47ba-render-")
    srv, ca = os.path.join(tmp, "server"), os.path.join(tmp, "ca", "pki")
    os.makedirs(srv)
    os.makedirs(ca)
    p = render_server_conf(proto="udp", port=1194, server_dir=srv, ca_dir=ca, dns="1.1.1.1")
    c1 = open(p, encoding="utf-8").read()
    p = render_server_conf(proto="udp", port=1194, server_dir=srv, ca_dir=ca, dns="8.8.8.8")
    c2 = open(p, encoding="utf-8").read()
    record("R1", c1 != c2 and "8.8.8.8" in c2, "DNS line re-rendered" if c1 != c2 else "file unchanged")

    try:
        render_server_conf(proto="tcp", port=443, server_dir=srv, ca_dir=ca, dns="8.8.8.8")
        record("R5", False, "port change silently applied")
    except Exception as e:
        record("R5", True, "refused: %s" % str(e)[:60])

    install_sh = os.path.join(TREE, "install.sh")
    try:
        fn_src = extract_fn(install_sh, "_restart_openvpn_if_conf_changed")
    except ValueError:
        for n in ("R2", "R3", "R4"):
            record(n, False, "_restart_openvpn_if_conf_changed absent (baseline defect)")
        shutil.rmtree(tmp, ignore_errors=True)
        return
    fn_path = os.path.join(tmp, "restart-fn.sh")
    with open(fn_path, "w") as f:
        f.write("log() { echo \"LOG: $*\"; }\n"
                "die() { echo \"DIE: $*\"; exit 42; }\n" + fn_src)
    conf = os.path.join(tmp, "server.conf")
    with open(conf, "w") as f:
        f.write("proto udp\nport 1194\npush \"dhcp-option DNS 1.1.1.1\"\n")

    def run_restart(before):
        cmd = "source %s; _restart_openvpn_if_conf_changed %s %s %s" % (
            fn_path, before or "EMPTY", conf, UNIT)
        out = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        return out.returncode, out.stdout + out.stderr

    def sha(p):
        return sh("sha256sum %s" % p).stdout.split()[0]

    cleanup_units()
    write_unit(UNIT_PATH, "/bin/sleep infinity", restart="no")
    sh("systemctl enable --now %s" % UNIT)
    ok = wait_active(UNIT)
    if not ok:
        for n in ("R2", "R3", "R4"):
            record(n, False, "dummy unit did not start")
        shutil.rmtree(tmp, ignore_errors=True)
        cleanup_units()
        return
    # R2: conf changed + active -> PID changes
    before = sha(conf)
    with open(conf, "w") as f:
        f.write("proto udp\nport 1194\npush \"dhcp-option DNS 8.8.8.8\"\n")
    pid1 = unit_pid(UNIT)
    rc, _ = run_restart(before)
    pid2 = unit_pid(UNIT)
    record("R2", rc == 0 and pid1 > 0 and pid2 > 0 and pid1 != pid2,
           "pid %d -> %d" % (pid1, pid2))
    # R3: conf unchanged -> no restart
    before = sha(conf)
    pid1 = unit_pid(UNIT)
    rc, _ = run_restart(before)
    pid2 = unit_pid(UNIT)
    record("R3", rc == 0 and pid1 == pid2, "pid stable %d" % pid1)
    # R4: conf changed + inactive -> returns 0, stays inactive
    sh("systemctl stop %s" % UNIT)
    with open(conf, "w") as f:
        f.write("proto udp\nport 1194\npush \"dhcp-option DNS 9.9.9.9\"\n")
    rc, _ = run_restart(before)
    record("R4", rc == 0 and not unit_active(UNIT), "rc=%d, still inactive" % rc)
    shutil.rmtree(tmp, ignore_errors=True)
    cleanup_units()


# ---------------------------------------------------------------- W: steady gate
def section_wait():
    install_sh = os.path.join(TREE, "install.sh")
    try:
        steady_src = extract_fn(install_sh, "_unit_steady")
        wait_src = extract_fn(install_sh, "wait_steady_active")
    except ValueError:
        for n in ("W1", "W2"):
            record(n, False, "wait_steady_active/_unit_steady not found")
        return
    tmp = tempfile.mkdtemp(prefix="r47ba-wait-")
    fn_path = os.path.join(tmp, "wait-fn.sh")
    with open(fn_path, "w") as f:
        f.write("log() { echo \"LOG: $*\"; }\n"
                "die() { echo \"DIE: $*\"; exit 42; }\n" + steady_src + wait_src)
    cmd = "source %s; wait_steady_active %s" % (fn_path, UNIT)

    # W1: one historical auto-restart (NRestarts=1, healthy) must pass
    cleanup_units()
    write_unit(UNIT_PATH, "/bin/sleep infinity", restart="on-failure")
    sh("systemctl enable --now %s" % UNIT)
    if not wait_active(UNIT):
        record("W1", False, "dummy unit did not start")
    else:
        pid = unit_pid(UNIT)
        sh("kill -9 %d" % pid)
        if not wait_nrestarts(UNIT, 1) or not wait_active(UNIT):
            record("W1", False, "auto-restart did not produce NRestarts=1")
        else:
            out = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=60)
            record("W1", out.returncode == 0,
                   "rc=%d %s" % (out.returncode, (out.stdout + out.stderr).strip().splitlines()[-1][:80] if (out.stdout + out.stderr).strip() else ""))
    cleanup_units()

    # W2: a restart DURING the settle window must still die, and the
    # message must name reset-failed. Drive it with a background kill.
    write_unit(UNIT_PATH, "/bin/sleep infinity", restart="on-failure")
    sh("systemctl enable --now %s" % UNIT)
    if not wait_active(UNIT):
        record("W2", False, "dummy unit did not start")
    else:
        proc = subprocess.Popen(["bash", "-c", cmd], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        time.sleep(1.5)  # inside the 5 s settle sleep after the first steady probe
        pid = unit_pid(UNIT)
        if pid > 0:
            sh("kill -9 %d" % pid)
        try:
            out, _ = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
        died = proc.returncode != 0
        names_remedy = "reset-failed" in out
        record("W2", died and names_remedy,
               "rc=%d remedy-named=%s" % (proc.returncode, names_remedy))
    cleanup_units()
    shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- U: uninstall
def section_uninstall():
    readme = open(os.path.join(TREE, "README.md"), encoding="utf-8").read()
    m = re.search(r"## 卸载.*?```bash\n(.*?)```", readme, re.S)
    block = m.group(1) if m else ""
    record("U2a", "<网卡>" not in readme, "no literal <网卡> in README")
    record("U2b", "ip route show default" in block, "real interface lookup in uninstall block")
    record("U2c", "caddy-installed" in block and "systemctl disable --now caddy" in block
           and not re.search(r"^systemctl disable --now caddy$", block, re.M),
           "caddy disable conditional on marker")
    record("U2d", "/var/log/openvpn" in block, "log dir cleanup in block")
    record("U2e", "uninstall-agent.sh" in block, "agent uninstall invoked in block")
    record("U2f", "caddy-stable.list" in block and "caddy-stable-archive-keyring" in block,
           "apt source + keyring cleanup in block")

    agent_readme = open(os.path.join(TREE, "agent", "README.md"), encoding="utf-8").read()
    record("U3", "## 卸载" in agent_readme and "uninstall-agent.sh" in agent_readme,
           "agent README uninstall section")

    install_sh = open(os.path.join(TREE, "install.sh"), encoding="utf-8").read()
    marker = "/etc/openvpn-sk5-panel/caddy-installed"
    # the installer writes "$CONFIG_DIR/caddy-installed"; resolve the variable
    config_dir = re.search(r'^CONFIG_DIR="([^"]+)"', install_sh, re.M)
    marker_in_installer = ("caddy-installed" in install_sh
                           and config_dir is not None
                           and config_dir.group(1) == "/etc/openvpn-sk5-panel")
    record("U4", marker_in_installer and marker in block,
           "marker written by installer (via $CONFIG_DIR), read by uninstall block")

    index = open(os.path.join(TREE, "panel", "templates", "index.html"), encoding="utf-8").read()
    record("U5", "uninstall-agent.sh" in index, "revoke dialog names uninstall-agent.sh")

    # U1: run the real script against fake roots + a real dummy unit
    script = os.path.join(TREE, "agent", "uninstall-agent.sh")
    if not os.path.isfile(script):
        record("U1", False, "agent/uninstall-agent.sh absent (baseline defect)")
        return
    tmp = tempfile.mkdtemp(prefix="r47ba-uninst-")
    fake_root = os.path.join(tmp, "opt", "ovpn-agent")
    fake_cfg = os.path.join(tmp, "etc", "ovpn-agent")
    os.makedirs(fake_root)
    os.makedirs(fake_cfg)
    with open(os.path.join(fake_root, "agent.py"), "w") as f:
        f.write("# stand-in\n")
    with open(os.path.join(fake_cfg, "config.json"), "w") as f:
        f.write("{}\n")
    cleanup_units()
    write_unit(AGENT_UNIT_PATH, "/bin/sleep infinity", restart="no")
    sh("systemctl enable --now %s" % AGENT_UNIT)
    if not wait_active(AGENT_UNIT):
        record("U1", False, "dummy agent unit did not start")
        shutil.rmtree(tmp, ignore_errors=True)
        cleanup_units()
        return
    env = {**os.environ,
           "OVPN_AGENT_INSTALL_ROOT": fake_root,
           "OVPN_AGENT_CONFIG_DIR": fake_cfg,
           "OVPN_AGENT_UNIT_FILE": AGENT_UNIT_PATH}
    out = subprocess.run(["bash", script, "--yes"], env=env, capture_output=True, text=True)
    ok = (out.returncode == 0 and not os.path.exists(fake_root)
          and not os.path.exists(fake_cfg) and not os.path.exists(AGENT_UNIT_PATH)
          and not unit_active(AGENT_UNIT))
    record("U1", ok, "rc=%d roots-gone=%s unit-stopped=%s"
           % (out.returncode, not os.path.exists(fake_root), not unit_active(AGENT_UNIT)))
    out2 = subprocess.run(["bash", script, "--yes"], env=env, capture_output=True, text=True)
    record("U1b", out2.returncode == 0 and "not installed" in out2.stdout,
           "second run clean no-op rc=%d" % out2.returncode)
    shutil.rmtree(tmp, ignore_errors=True)
    cleanup_units()


def main():
    if os.geteuid() != 0:
        print("must run as root (systemd cells)")
        return 2
    if sh("systemctl is-system-running").returncode != 0:
        print("systemd not running; cannot run")
        return 2
    try:
        section_hash()
        section_render()
        section_wait()
        section_uninstall()
    finally:
        cleanup_units()
    failed = sum(1 for _, v, _ in RESULTS if v == "FAIL")
    print("TOTAL: %d cells, %d FAIL" % (len(RESULTS), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
