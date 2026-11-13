#!/usr/bin/env python3
"""OpenVPN + SK5 单页轻量面板.

后端: Flask + SQLite(仅存管理员密码哈希与会话密钥).
业务逻辑不在本文件: OpenVPN 侧调用 core/openvpn_manager.py(真实接口,
见 README 对接点),SK5 出口侧调用 egress/sk5_manager.py. 对接模块未
落盘时,相关接口返回 503 并明示缺失模块,面板登录页与静态页仍可访问.
启动: python3 app.py (监听 0.0.0.0:8443)
安全模型见 docs/security.md:随机管理员口令(无默认值)、登录限流、
节点 token + panel_url 认领守卫、审计日志、SK5 凭据永不回显/不进日志。
"""
import gzip
import hashlib
import inspect
import io
import json
import os
import re
import secrets
import socket
import sqlite3
import sys
import tarfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
for _p in (os.path.join(PROJECT_DIR, "core"),
           os.path.join(PROJECT_DIR, "egress")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from flask import (Flask, jsonify, request, send_file,
                   send_from_directory, session)
from werkzeug.middleware.proxy_fix import ProxyFix

try:
    import bcrypt as _bcrypt
except ImportError:  # noqa: BLE001 - 极简环境无 bcrypt 时回落旧哈希
    _bcrypt = None

# ---- 对接点: core/openvpn_manager.py (真实接口,见 README) ----
_IMPORT_ERRORS = {}
try:
    from openvpn_manager import (UserAlreadyExistsError,
                                 UserAlreadyRevokedError,
                                 UserNotFoundError, build_client_config,
                                 create_user, detect_public_ip,
                                 ip_is_private, list_users,
                                 render_server_conf, restart_server,
                                 revoke_user, server_status, start_server,
                                 stop_server, validate_username)
except Exception as exc:  # noqa: BLE001 - core 尚未落盘时记录,接口报 503
    _IMPORT_ERRORS["openvpn_manager"] = str(exc)
    build_client_config = create_user = list_users = None
    render_server_conf = restart_server = revoke_user = None
    server_status = start_server = stop_server = validate_username = None
    detect_public_ip = ip_is_private = None
    UserAlreadyExistsError = UserAlreadyRevokedError = None
    UserNotFoundError = None

# ---- 对接点: egress/sk5_manager.py (真实接口,见 README) ----
try:
    from sk5_manager import (CONFIG_FILE as SK5_CONFIG_FILE,
                             current_egress_ip, enable as sk5_enable_fn,
                             disable as sk5_disable_fn,
                             get_status as sk5_get_status,
                             set_fail_open as sk5_set_fail_open,
                             set_sk5 as sk5_set_sk5,
                             set_udp_over_tcp as sk5_set_udp_over_tcp,
                             test_sk5 as sk5_test_proxy)
except Exception as exc:  # noqa: BLE001 - egress 尚未落盘时记录,接口报 503
    _IMPORT_ERRORS["sk5_manager"] = str(exc)
    sk5_get_status = sk5_set_sk5 = sk5_test_proxy = None
    current_egress_ip = sk5_enable_fn = sk5_disable_fn = None
    sk5_set_fail_open = sk5_set_udp_over_tcp = None
    SK5_CONFIG_FILE = None

# egress 的 set_sk5() 是否支持部分合并 + clear_password（AUDIT-R1
# P0-2/P0-4 要求的契约）：新版支持，password=None/"" 保留已存密码，
# clear_password=True 才清空；旧版是全量覆盖、无此参数。
# 面板按实际签名自适应（见 sk5_save），新旧 egress 都能正确工作。
try:
    _SK5_ACCEPTS_CLEAR = (sk5_set_sk5 is not None and "clear_password" in
                          inspect.signature(sk5_set_sk5).parameters)
except (TypeError, ValueError):
    _SK5_ACCEPTS_CLEAR = False

# R2-P2-2: the data directory (DB, admin.pass, secret, agent queue,
# server settings) is overridable with OVPN_PANEL_DATA_DIR; unset, it
# stays panel/data as before. install.sh writes the variable into
# panel.env pointing at the installed data dir. _secret_path() keeps
# its own env priority (OVPN_PANEL_SECRET_PATH, then /etc/..., then
# DATA_DIR/secret.key) and is unaffected.
DATA_DIR = os.environ.get("OVPN_PANEL_DATA_DIR") or os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "panel.db")


def _secret_path():
    """Flask 会话密钥的存放位置。

    密钥绝不许落在项目树里：`import app` 就在模块级调
    `_load_or_create_secret()`，密钥若默认放 `panel/data/`，任何一次
    导入/测试都会把一个活密钥重新生成进发货树（P0-5 复发）。
    顺序：显式环境变量 > /etc（机器级位置，部署与开发共用）>
    `panel/data/`（仅当 /etc 不可写时，如 nobody 身份的测试副本）。"""
    env = os.environ.get("OVPN_PANEL_SECRET_PATH")
    if env:
        return env
    etc = "/etc/openvpn-sk5-panel/secret.key"
    parent = os.path.dirname(etc)
    try:
        if os.path.exists(etc) or os.access(parent, os.W_OK):
            return etc
        if not os.path.exists(parent) and os.access("/etc", os.W_OK):
            return etc
    except OSError:
        pass
    return os.path.join(DATA_DIR, "secret.key")


SECRET_PATH = _secret_path()
ADMIN_PASS_PATH = "/etc/openvpn-sk5-panel/admin.pass"
ADMIN_PASS_FALLBACK = os.path.join(DATA_DIR, "admin.pass")

# core 子网/DNS 由 server.conf.template 固定,面板不提供修改入口
FIXED_SUBNET = "10.8.0.0/24"
FIXED_DNS = "1.1.1.1"
CA_DIR = Path(os.environ.get("OPENVPN_CA_DIR", "/etc/openvpn/server/easy-rsa"))
SERVER_DIR = Path(os.environ.get("OPENVPN_SERVER_DIR", "/etc/openvpn/server"))

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))


# P0-5：曾随项目树发货的 secret.key 的 SHA-256（该密钥本身已公开，
# 任何持仓者都知道它；只用哈希做"发货值"检测，哈希反推不出密钥）。
# 启动时若读到的文件就是这个值，立即强制轮换；项目树里的
# panel/data/secret.key 已删除，install.sh 装机时也不再拷贝它。
_SHIPPED_SECRET_SHA256 = (
    "484fec07e813e9b9e57548d1992ce6767326fd8a82cfddd6fe0c595f93d7d5a5")


def _load_or_create_secret():
    parent = os.path.dirname(SECRET_PATH)
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError:
        pass
    if os.path.exists(SECRET_PATH):
        with open(SECRET_PATH, "rb") as f:
            key = f.read()
        if (len(key) == 32 and hashlib.sha256(key).hexdigest()
                == _SHIPPED_SECRET_SHA256):
            key = secrets.token_bytes(32)
            with open(SECRET_PATH, "wb") as f:
                f.write(key)
            os.chmod(SECRET_PATH, 0o600)
            print("WARNING: 检测到发货自带的 secret.key（已公开），"
                  "已强制轮换，旧值作废", flush=True)
            return key
        try:
            os.chmod(SECRET_PATH, 0o600)
        except OSError:
            pass
        return key
    key = secrets.token_bytes(32)
    with open(SECRET_PATH, "wb") as f:
        f.write(key)
    os.chmod(SECRET_PATH, 0o600)
    return key


app.secret_key = _load_or_create_secret()
# P2-1：只在显式声明受信反代时才信 X-Forwarded-For。默认不信任任何
# 头——否则攻击者伪造 X-Forwarded-For 即可绕过按 IP 的登录限流。
if os.environ.get("OVPN_TRUSTED_PROXY", "0") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Secure 标记只在 TLS 部署时开（OVPN_PANEL_HTTPS=1）：面板本体是明文
# HTTP 8443，前面挂 TLS 反代/wrapper 时置 1；本机明文调试保持 0，
# 否则浏览器会直接丢弃会话 cookie 导致登录后立刻掉线。
app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get("OVPN_PANEL_HTTPS", "0") == "1")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=12)

# ---- 安全常量（见 docs/security.md）----
LOGIN_MAX_FAILURES = 5       # 同一 IP 5 分钟内 5 次失败即锁
LOGIN_WINDOW_SECONDS = 300
LOGIN_LOCK_SECONDS = 900     # 锁 15 分钟
AGENT_QUEUE_PATH = os.path.join(DATA_DIR, "agent_queue.json")
# agent 动作白名单：与 agent/agent.py 的 ACTIONS 逐字一致，非法一律 400。
AGENT_ACTIONS = frozenset({
    "install_prereqs", "init_pki", "create_server",
    "start_openvpn", "stop_openvpn", "restart_openvpn",
    "create_user", "revoke_user", "set_sk5", "test_sk5",
    "enable_sk5", "disable_sk5", "get_status",
})
_NODE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_SECRET_KEYS = {"password", "node_token", "token"}
_SECRET_KV_RE = re.compile(
    r'("(?:password|node_token|token)"\s*:\s*")[^"]*', re.IGNORECASE)


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS admin "
                 "(id INTEGER PRIMARY KEY CHECK (id = 1), "
                 " password_hash TEXT NOT NULL, "
                 " session_version INTEGER NOT NULL DEFAULT 1)")
    # 存量库迁移：给旧 admin 表补 session_version 列（改密作废旧会话用）。
    try:
        conn.execute("ALTER TABLE admin ADD COLUMN "
                     "session_version INTEGER NOT NULL DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    # P2-1：登录限流计数进 SQLite（重启不丢），替代旧的进程内内存 dict。
    conn.execute("CREATE TABLE IF NOT EXISTS login_attempts "
                 "(ip TEXT PRIMARY KEY, "
                 " failures TEXT NOT NULL DEFAULT '[]', "
                 " locked_until REAL NOT NULL DEFAULT 0)")
    # 节点注册：token 明文永不入库，只存 SHA-256 哈希；panel_url 是
    # 注册时绑定的面板地址（认领守卫用，见 _check_panel_claim）。
    conn.execute("CREATE TABLE IF NOT EXISTS nodes "
                 "(name TEXT PRIMARY KEY, "
                 " token_hash TEXT NOT NULL, "
                 " panel_url TEXT, "
                 " created_at TEXT NOT NULL, "
                 " last_seen TEXT, "
                 " last_status TEXT)")
    # 管理操作审计：detail 在写入前已脱敏（见 _redact_text），
    # 绝不含口令、节点 token、.ovpn 私钥。
    conn.execute("CREATE TABLE IF NOT EXISTS audit_log "
                 "(id INTEGER PRIMARY KEY AUTOINCREMENT, "
                 " ts TEXT NOT NULL, "
                 " actor TEXT NOT NULL, "
                 " action TEXT NOT NULL, "
                 " node TEXT NOT NULL DEFAULT '', "
                 " result TEXT NOT NULL, "
                 " detail TEXT NOT NULL DEFAULT '')")
    conn.commit()
    try:
        os.chmod(DB_PATH, 0o600)
    except OSError:
        pass
    return conn


def _hash_password(password):
    """管理员密码哈希：bcrypt 为主（P2-5，与 FLMX 对齐）。

    bcrypt 未安装的极简环境回落旧的加盐 SHA-256（格式 "salt:digest"，
    _check_password 能识别两种格式）。"""
    if _bcrypt is not None:
        return _bcrypt.hashpw(password.encode("utf-8"),
                              _bcrypt.gensalt()).decode("ascii")
    salt = secrets.token_hex(16)
    digest = hashlib.sha256((salt + password).encode()).hexdigest()
    return salt + ":" + digest


def _check_password(password, stored):
    """验密。bcrypt 哈希走 bcrypt；旧 "salt:digest" 哈希走 SHA-256，
    验过即返回 True（调用方负责透明迁移到 bcrypt，见 login）。"""
    if not isinstance(stored, str) or not stored:
        return False
    if stored.startswith("$2"):
        if _bcrypt is None:
            return False
        try:
            return _bcrypt.checkpw(password.encode("utf-8"),
                                   stored.encode("ascii"))
        except (ValueError, TypeError):
            return False
    try:
        salt, digest = stored.split(":", 1)
    except ValueError:
        return False
    return secrets.compare_digest(
        hashlib.sha256((salt + password).encode()).hexdigest(), digest)


def _session_version():
    """当前会话版本号：改密后 +1，全部旧会话失效（P1-7）。"""
    try:
        conn = _db()
        row = conn.execute(
            "SELECT session_version FROM admin WHERE id = 1").fetchone()
        conn.close()
        return int(row["session_version"]) if row else 1
    except Exception:  # noqa: BLE001 - 读不到时按 1 处理，不阻塞登录
        return 1


# R31-P2-2: bcrypt 5.x hashpw raises ValueError past 72 bytes; the
# boundary is by UTF-8 bytes, not characters (25 CJK chars already
# exceed it). Reject over-long passwords at validation time with a
# 400 that names the byte limit, and keep a ValueError guard around
# _hash_password in change_password as defense in depth.
_BCRYPT_MAX_BYTES = 72
_PASSWORD_TOO_LONG = "新密码超过 72 字节上限（按 UTF-8 字节计，bcrypt 限制）"


def _validate_new_password(old, new):
    """新密码强度：>=12 字符、含字母与数字、与旧密码不同、UTF-8 不超过 72 字节。"""
    if len(new) < 12:
        return False, "新密码至少 12 个字符"
    if not re.search(r"[A-Za-z]", new) or not re.search(r"[0-9]", new):
        return False, "新密码须同时包含字母和数字"
    if len(new.encode("utf-8")) > _BCRYPT_MAX_BYTES:
        return False, _PASSWORD_TOO_LONG
    if new == old:
        return False, "新密码不能与旧密码相同"
    return True, ""


def _ensure_admin_password():
    """首次启动生成随机管理员密码,打印到 stdout 并写文件(600)."""
    conn = _db()
    row = conn.execute("SELECT password_hash FROM admin WHERE id = 1").fetchone()
    if row:
        conn.close()
        return None
    password = secrets.token_urlsafe(16)
    conn.execute("INSERT INTO admin (id, password_hash) VALUES (1, ?)",
                 (_hash_password(password),))
    conn.commit()
    conn.close()
    path = ADMIN_PASS_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(password + "\n")
        os.chmod(path, 0o600)
    except OSError:
        path = ADMIN_PASS_FALLBACK
        with open(path, "w") as f:
            f.write(password + "\n")
        os.chmod(path, 0o600)
    print("=" * 60, flush=True)
    print("OpenVPN-SK5 面板首次启动,管理员密码已生成:", flush=True)
    print("  密码: %s" % password, flush=True)
    print("  已写入: %s (600)" % path, flush=True)
    print("=" * 60, flush=True)
    return password


# ---------------- 安全：脱敏、审计、登录限流 ----------------

def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _redact_text(text):
    """把文本里 password/node_token/token 键的值替换为 ***。"""
    if not isinstance(text, str):
        text = str(text)
    return _SECRET_KV_RE.sub(r"\1***", text)


def _redact_dict(obj):
    """递归脱敏：删掉密码/token 键的值；超长字符串截断（防 .ovpn
    私钥整段混进日志/快照）。"""
    if isinstance(obj, dict):
        return {k: ("***" if str(k).lower() in _SECRET_KEYS
                    else _redact_dict(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_dict(v) for v in obj]
    if isinstance(obj, str) and len(obj) > 2000:
        return obj[:2000] + "...[truncated]"
    return obj


def _audit(action, actor="admin", node="", result="ok", detail=""):
    """写一条审计日志。调用方只传已脱敏的 detail；这里再脱敏一次兜底。"""
    try:
        conn = _db()
        conn.execute(
            "INSERT INTO audit_log (ts, actor, action, node, result, detail)"
            " VALUES (?,?,?,?,?,?)",
            (_utcnow_iso(), actor, action, node, result,
             _redact_text(detail)[:500]))
        conn.commit()
        conn.close()
    except Exception:  # noqa: BLE001 - 审计失败不阻塞业务
        pass


def _login_attempts_row(ip):
    """读某 IP 的限流记录（failures 为窗口内失败时间戳列表）。"""
    conn = _db()
    row = conn.execute(
        "SELECT failures, locked_until FROM login_attempts WHERE ip = ?",
        (ip,)).fetchone()
    conn.close()
    if not row:
        return [], 0.0
    try:
        failures = json.loads(row["failures"])
    except ValueError:
        failures = []
    now = time.time()
    failures = [t for t in failures
                if isinstance(t, (int, float))
                and now - t < LOGIN_WINDOW_SECONDS]
    return failures, float(row["locked_until"] or 0)


def _login_locked_until(ip):
    failures, locked = _login_attempts_row(ip)
    if locked and time.time() < locked:
        return locked
    return None


def _record_login_failure(ip):
    """记一次登录失败（限流记账）。写盘失败不阻塞登录 verdict，
    与 _audit 同待遇（R9-P2-2：磁盘满时登录端点 500）。
    写丢只意味着本次失败未计入限流窗口——锁不住时不谎称已锁：
    _login_locked_until 只读已落盘的行，无行即无锁。"""
    try:
        now = time.time()
        failures, locked = _login_attempts_row(ip)
        failures.append(now)
        if len(failures) >= LOGIN_MAX_FAILURES:
            locked = now + LOGIN_LOCK_SECONDS
            failures = []
        conn = _db()
        try:
            conn.execute(
                "INSERT INTO login_attempts (ip, failures, locked_until)"
                " VALUES (?,?,?) ON CONFLICT(ip) DO UPDATE SET"
                " failures=excluded.failures, locked_until=excluded.locked_until",
                (ip, json.dumps(failures), locked))
            # 顺带清掉已过期且无失败记录的行，表不无限长大。
            conn.execute("DELETE FROM login_attempts WHERE locked_until < ?"
                         " AND failures = '[]'", (now,))
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - 限流记账失败不阻塞登录
        pass


def _clear_login_failures(ip):
    """清某 IP 的失败记录。写盘失败不阻塞登录（R9-P2-2），与 _audit
    同待遇；清不掉只会让该 IP 的失败计数多留一轮（偏严方向），
    不会谎称已锁、也不会把正确登录挡在门外。"""
    try:
        conn = _db()
        try:
            conn.execute("DELETE FROM login_attempts WHERE ip = ?", (ip,))
            conn.commit()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - 清失败记录失败不阻塞登录
        pass


# ---------------- 安全：agent 命令队列（内存 + JSON 文件持久化） ----------------
# 队列文件含 set_sk5 的密码与 create_user 回执的 .ovpn（含私钥），
# 故文件本身 0600，且只进审计脱敏后的摘要，不进日志。

_QUEUE_LOCK = threading.Lock()


def _queue_loss_counts(state):
    """隔离时丢失的命令计数（R21-P2-1）。返回 (queued, sent, ovpn)，
    每项为 int 或字符串 "不可知"。state 为 None（整文件不可解析／
    顶层非对象）时三项全不可知；state 为 dict 时（某段非对象）从
    可读段里数，坏段本身记不可知。只数字段，不读条目内容。"""
    if not isinstance(state, dict):
        return ("不可知", "不可知", "不可知")
    queue = state.get("queue")
    if isinstance(queue, dict):
        if any(not isinstance(v, list) for v in queue.values()):
            queued = "不可知"
        else:
            queued = sum(len(v) for v in queue.values())
    else:
        queued = "不可知"
    cmds = state.get("cmds")
    if isinstance(cmds, dict):
        sent = sum(1 for c in cmds.values()
                   if isinstance(c, dict) and c.get("status") == "sent")
    else:
        sent = "不可知"
    ovpn = state.get("ovpn")
    ovpn_n = len(ovpn) if isinstance(ovpn, dict) else "不可知"
    return (queued, sent, ovpn_n)


def _quarantine_corrupt_queue(error, state=None):
    """损坏的队列文件改名备份并告警（R9-P2-1），同时写一条审计行（R21-P2-1）。
    备份名带 UTC 时间戳（微秒），不覆盖旧备份。告警与审计只写路径与
    解析错误，不写文件内容——队列里含 set_sk5 密码与 .ovpn 私钥，
    绝不能进日志。调用方须已持 _QUEUE_LOCK（全部 _load_queue
    调用点均在锁内），改名不会与并发写盘撞上。审计写 panel.db：
    与 _fail_malformed_cmds 的 queue_malformed 行同款——_audit 自带
    try/except 且用独立 sqlite 连接，在锁内调用安全，不会死锁。
    丢失计数口径见 _queue_loss_counts：不可解析时如实写“不可知”，
    不编 0；某段非对象时从已解析状态里数。返回备份路径，备份失败
    （原文件仍在原地）时返回 None——调用方据此决定是否可安全返空。
    （R23-P2-3：不可读文件也走本函数隔离；备份失败时调用方不得返空，
    否则随后 _save_queue 会把未备份的命令物理销毁。）"""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    backup = "%s.corrupt.%s" % (AGENT_QUEUE_PATH, stamp)
    try:
        os.replace(AGENT_QUEUE_PATH, backup)
    except OSError:
        backup = None
    print("WARNING: agent queue file %s is corrupt (%s); quarantined to %s"
          % (AGENT_QUEUE_PATH, error,
             backup if backup else "FAILED to move"),
          file=sys.stderr, flush=True)
    queued, sent, ovpn_n = _queue_loss_counts(state)
    _audit("queue_corrupt_quarantined", result="failed",
           detail="队列文件已隔离备份至 %s（损坏原因：%s）；丢失 queued=%s sent=%s .ovpn 回执=%s；备份文件可手工恢复"
           % (backup if backup else "备份失败（原文件仍在原地）",
              error, queued, sent, ovpn_n))
    return backup


def _load_queue():
    """读队列文件。文件不存在是正常初态（空队列，无审计行）；文件存在但
    解析失败或解析出的不是 dict，是损坏——R9-P2-1：不得静默丢弃，
    改名 .corrupt 备份＋stderr 告警＋审计行（R21-P2-1），操作员可手动恢复；本轮返回
    空队列，面板继续工作（调用方随后 _save_queue 写回全新空队列）。
    文件存在但不可读（OSError，如权限错）与解析失败同待遇（R23-P2-3）：
    先隔离备份＋审计行再返空——否则调用方随后 _save_queue 会把不可读
    文件里的已排队命令物理销毁且零痕迹。隔离失败（备份 rename 不成）
    时宁可大声失败（raise）也不返空：返空后写回即销毁命令，而备份又
    不在——正是本缺陷的静默销毁。所有 _save_queue 调用点都在同一
    _QUEUE_LOCK 内、紧跟本次 _load_queue，故加载点隔离＋失败即 raise
    已覆盖全部写回路径，无须改 _save_queue；隔离成功后写回的是全新
    空队列（原命令保存在 .corrupt 备份里，可手工恢复），与 BN 的
    解析失败分支取舍一致。"""
    try:
        with open(AGENT_QUEUE_PATH, encoding="utf-8") as f:
            raw = f.read()
    except FileNotFoundError:
        return {"queue": {}, "cmds": {}, "ovpn": {}}
    except OSError as exc:
        backup = _quarantine_corrupt_queue(
            "queue file unreadable: %s" % exc)
        if backup is None:
            raise RuntimeError(
                "agent queue file %s is unreadable (%s) and could not be "
                "quarantined; refusing to return an empty queue" % (
                    AGENT_QUEUE_PATH, exc))
        return {"queue": {}, "cmds": {}, "ovpn": {}}
    try:
        state = json.loads(raw)
    except ValueError as exc:
        _quarantine_corrupt_queue(exc)
        return {"queue": {}, "cmds": {}, "ovpn": {}}
    if not isinstance(state, dict):
        _quarantine_corrupt_queue("top-level JSON is not an object")
        return {"queue": {}, "cmds": {}, "ovpn": {}}
    state.setdefault("queue", {})
    state.setdefault("cmds", {})
    state.setdefault("ovpn", {})
    for _section in ("queue", "cmds", "ovpn"):
        if not isinstance(state.get(_section), dict):
            # R12-P1-1：手改队列文件把某段写成非对象时，与损坏 JSON
            # 同待遇——整文件隔离备份，不让后续 .get() 抛错 wedge 通道。
            # state 本身已解析出，把它传给隔离函数数丢失计数（R21-P2-1）。
            _quarantine_corrupt_queue(
                "queue section %r is not an object" % _section, state)
            return {"queue": {}, "cmds": {}, "ovpn": {}}
    return state


def _save_queue(state):
    tmp = AGENT_QUEUE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
        f.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, AGENT_QUEUE_PATH)
    os.chmod(AGENT_QUEUE_PATH, 0o600)


def _enqueue_command(node_name, action, params):
    cmd = {"id": uuid.uuid4().hex, "node": node_name, "action": action,
           "params": params or {}, "status": "queued", "result": None,
           "error": None, "created_at": _utcnow_iso(), "sent_at": None,
           "finished_at": None, "retries": 0}
    with _QUEUE_LOCK:
        state = _load_queue()
        # R14-P2-1：先隔离坏条目——手改队列把某节点队列值写成非列表时，
        # 下面的 .append 会在其上抛 AttributeError；扫过之后才安全。
        _fail_malformed_cmds(state)
        state["cmds"][cmd["id"]] = cmd
        state["queue"].setdefault(node_name, []).append(cmd["id"])
        _save_queue(state)
    return cmd


# P1-6：命令 "sent" 态重投。agent 取走命令后若 120 秒未回执
# （崩溃/离线/回执丢失），命令不再永久卡住：自动打回 queued
# 重新下发，最多重投 3 次，超过即标 failed。
# 与 Worker 侧约定一致：状态机 queued -> sent -> done/failed，
# 超时重投时 retries +1；非幂等命令（create_user/init_pki）重投
# 时 agent 侧可能重复执行，见 docs/security.md。
SENT_TIMEOUT_SECONDS = 120
SENT_MAX_RETRIES = 3


_CMD_STATUSES = ("queued", "sent", "done", "failed")


def _fail_malformed_cmds(state):
    """R12-P1-1：扫一遍队列，把字段缺失/错型的命令标 failed 并写审计行。

    只处理非终态（queued/sent/缺 status/错 status）的条目；已是
    done/failed 的不再重复审计。调用方须已持 _QUEUE_LOCK；改动由
    调用方随后的 _save_queue(state) 落盘。返回标 failed 的 id 列表。
    手改 agent_queue.json 是现实排障操作，一条坏记录绝不能再楔死
    poll/cmd_get/report 全通道。审计 detail 只记字段名，不记字段值
    （params 里可能有 SK5 密码、result 里可能有 .ovpn 私钥）。
    R13-P2-1：sent 态命令的 sent_at 还须可解析——缺失／不可解析
    的 sent_at 在 _requeue_stale_sent 里只会被跳过、命令永久滞留，
    故在此直接标 failed＋审计。
    R14-P2-1：同款隔离须覆盖全部三段——cmds 段之外，ovpn 段的非对象
    回执（node_user_ovpn 的 rec.get("ovpn") 会 500）一并删掉＋审计；
    queue 段某节点的值非列表时（_enqueue_command 与
    _requeue_stale_sent 的 .append 会 500）删该键＋审计。只删形状，
    不碰内容合法性：dict 形回执即使 ovpn 字段为空也不在此处动，
    下载路径自会 404。"""
    failed = []
    cmds = state.get("cmds") or {}
    queue = state.get("queue") or {}
    ovpn = state.get("ovpn") or {}
    for key, rec in list(ovpn.items()):
        if not isinstance(rec, dict):
            # 非对象回执无法下发：删掉＋审计（只记键，不记内容——
            # 回执里可能有 .ovpn 私钥）。删后下载路径回 404 而非 500。
            del ovpn[key]
            _audit("queue_ovpn_malformed", result="failed",
                   detail="key=%s 回执不是 JSON 对象，已丢弃" % key)
    for node, ids in list(queue.items()):
        if not isinstance(ids, list):
            # 某节点队列值非列表：_enqueue_command 与
            # _requeue_stale_sent 的 .append 会在其上抛 AttributeError。
            # 删该键＋审计（只记节点名）；该节点命令改走 cmds 段状态，
            # 不因此丢失——queued 命令仍在 cmds 里，poll 时无队列可取
            # 只会空转，不会 500。
            del queue[node]
            _audit("queue_malformed", node=node if isinstance(node, str) else "",
                   result="failed",
                   detail="node=%s 队列值不是列表，已丢弃" % node)
    for cid, cmd in list(cmds.items()):
        if not isinstance(cmd, dict):
            # 非对象条目无法原地标 failed：从 cmds 与各节点队列里删掉，
            # 审计行留痕（只记 id，不记内容）。
            del cmds[cid]
            for ids in queue.values():
                if isinstance(ids, list) and cid in ids:
                    ids.remove(cid)
            _audit("queue_cmd_malformed", result="failed",
                   detail="id=%s 条目不是 JSON 对象，已丢弃" % cid)
            failed.append(cid)
            continue
        if cmd.get("status") in ("done", "failed"):
            continue
        problems = []
        if cmd.get("id") != cid:
            # 键即 id；手改后不一致时以键为准修复。
            cmd["id"] = cid
        node = cmd.get("node")
        if not isinstance(node, str) or not node:
            problems.append("node 缺失/错型")
        action = cmd.get("action")
        if not isinstance(action, str) or action not in AGENT_ACTIONS:
            problems.append("action 缺失/非法")
        if not isinstance(cmd.get("params"), dict):
            problems.append("params 缺失/错型")
        status = cmd.get("status")
        if status is None:
            problems.append("status 缺失")
        elif status not in _CMD_STATUSES:
            problems.append("status 非法")
        if cmd.get("sent_at") is not None and not isinstance(
                cmd.get("sent_at"), str):
            problems.append("sent_at 错型")
        if status == "sent":
            # R13-P2-1：sent 态命令必须有可解析的 sent_at，否则状态机
            # 无出口（_requeue_stale_sent 的 fromisoformat 抛错后只
            # continue，命令永久滞留 sent）。缺失／不可解析一律标
            # failed＋审计，不再下发；queued 态的 sent_at 下发时会被
            # 重写，垃圾值无害，不在此处拦。
            sent_at = cmd.get("sent_at")
            if sent_at is None:
                problems.append("sent_at 缺失")
            elif isinstance(sent_at, str):
                try:
                    datetime.fromisoformat(sent_at)
                except ValueError:
                    problems.append("sent_at 不可解析")
        if cmd.get("created_at") is not None and not isinstance(
                cmd.get("created_at"), str):
            problems.append("created_at 错型")
        if cmd.get("finished_at") is not None and not isinstance(
                cmd.get("finished_at"), str):
            problems.append("finished_at 错型")
        if (cmd.get("retries") is not None
                and _safe_int(cmd.get("retries")) is None):
            problems.append("retries 错型")
        if not problems:
            continue
        cmd["status"] = "failed"
        cmd["error"] = "队列条目损坏（%s），已隔离，不再下发" % "、".join(problems)
        cmd["finished_at"] = _utcnow_iso()
        _audit("queue_cmd_malformed",
               node=node if isinstance(node, str) else "",
               result="failed",
               detail="id=%s %s" % (cid, "、".join(problems)))
        failed.append(cid)
    return failed


def _requeue_stale_sent(state):
    """扫一遍 sent 态命令，超时的打回 queued 或标 failed。
    调用方须已持 _QUEUE_LOCK。返回 (重投 id 列表, 失败 id 列表)。"""
    now = datetime.now(timezone.utc)
    requeued, failed = [], []
    for cmd in state["cmds"].values():
        if not isinstance(cmd, dict):
            # R12-P1-1：非对象条目由 _fail_malformed_cmds 处理，
            # 此处只跳过，绝不 wedge。
            continue
        if cmd.get("status") != "sent" or not cmd.get("sent_at"):
            continue
        try:
            sent = datetime.fromisoformat(cmd.get("sent_at"))
        except (ValueError, TypeError):
            # 防御性跳过：正常路径上 _fail_malformed_cmds 已先把
            # sent_at 缺失／不可解析的 sent 命令标 failed（R13-P2-1），
            # 到这里的 sent 命令 sent_at 恒可解析；此分支只防直接
            # 调用本函数且未先扫队列的情形，绝不 wedge 整条队列。
            continue
        if sent.tzinfo is None:
            # R9-P1-1：naive 时间戳按 UTC 解读。fromisoformat 对无时区
            # 字符串成功，但与 aware 的 now 相减抛 TypeError，曾 wedge
            # 全部 agent 命令（poll 与 cmd_get 双双 500）；正常写入
            # 恒为 aware（_utcnow_iso 带 +00:00），naive 只可能来自
            # 手改队列文件，UTC 解读后按正常超时规则重投／失败。
            sent = sent.replace(tzinfo=timezone.utc)
        if (now - sent).total_seconds() <= SENT_TIMEOUT_SECONDS:
            continue
        retries = (_safe_int(cmd.get("retries")) or 0) + 1
        cmd["retries"] = retries
        if retries > SENT_MAX_RETRIES:
            cmd["status"] = "failed"
            cmd["error"] = ("agent 超过 %d 秒未回执，已重投 %d 次，放弃"
                            % (SENT_TIMEOUT_SECONDS, SENT_MAX_RETRIES))
            cmd["finished_at"] = _utcnow_iso()
            failed.append(cmd.get("id"))
        else:
            cmd["status"] = "queued"
            cmd["sent_at"] = None
            node = cmd.get("node")
            if node:
                q = state["queue"].setdefault(node, [])
                if cmd.get("id") not in q:
                    q.append(cmd.get("id"))
            requeued.append(cmd.get("id"))
    return requeued, failed


# ---------------- 安全：节点 token ----------------

def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _get_node(name):
    conn = _db()
    row = conn.execute(
        "SELECT name, token_hash, panel_url, created_at, last_seen,"
        " last_status FROM nodes WHERE name = ?", (name,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _lookup_node(name):
    """按名取节点；不存在即回 404（R11-P1-1：init-pki 与兼容层共用）。"""
    node = _get_node(name)
    if node is None:
        return None, (jsonify({"ok": False, "error": "节点不存在：%s" % name}), 404)
    return node, None


def _resolve_compat_node(data=None):
    """R11-P1-1：兼容层路由的节点解析（Worker resolveNode 的 Flask 等价物）。
    body.node > ?node= > X-Node；指名不存在即 404。未指定时返回 (None, None)
    ——调用方走本机执行（Flask 单节点部署与门禁的既有行为）；这与 Worker
    （未指定＋单节点自动／多节点 400）不同，是刻意保留的：门禁与单节点
    部署在无 ?node= 时一律期望本机执行，改成自动会把本机写操作误入队。
    前端已可把 currentNode 清空回 "" 取本机执行。"""
    name = ""
    if isinstance(data, dict):
        name = str(data.get("node") or "").strip()
    if not name:
        name = str(request.args.get("node") or "").strip()
    if not name:
        name = str(request.headers.get("X-Node") or "").strip()
    if not name:
        return None, None
    return _lookup_node(name)


def _enqueue_compat(node_name, action, params, audit_action, detail=""):
    """R11-P1-1：兼容层写操作指名远程节点时的入队回执。
    与 init-pki 完全同款（202 ＋ cmd_id ＋ queued: true），前端 apiWait
    已支持该形状（轮询 /api/cmd/:id 2s×60）。detail 追加到审计行
    （只放非敏感字段，绝不放密码）。"""
    cmd = _enqueue_command(node_name, action, params)
    _audit(audit_action, node=node_name, result="ok",
           detail="action=%s id=%s%s" % (action, cmd["id"], detail))
    return jsonify({"ok": True, "cmd_id": cmd["id"], "node": node_name,
                    "action": action, "status": "queued",
                    "queued": True}), 202


def _node_snapshot(node):
    """读某节点的已存状态快照（nodes.last_status：agent 上报的 get_status
    全量结果与心跳合并而成，见 _touch_node）。返回 (快照 dict 或 None,
    last_seen)。心跳形只有 version/hostname/openvpn_running/sk5_enabled
    四键，全量形另含 openvpn/users/sk5/egress_ip/health/at。"""
    try:
        raw = node.get("last_status")
        snap = json.loads(raw) if raw else None
    except ValueError:
        snap = None
    if not isinstance(snap, dict):
        snap = None
    return snap, node.get("last_seen")


def _snapshot_users(node):
    """节点快照顶层的 users 列表折成 {name: user}（R13-P2-3：三条
    下载路径共用同一形状）。无快照／users 不是列表时回空 dict。"""
    snap, _last_seen = _node_snapshot(node)
    raw_users = (snap or {}).get("users")
    users = {}
    if isinstance(raw_users, list):
        users = {u.get("name"): u for u in raw_users
                 if isinstance(u, dict)}
    return users


def _download_block_reason(status):
    """下载守卫（R13-P2-3）：吊销／过期一律禁下。返回禁下原因文案，
    可下时回 None。三条下载路径（本地／?node=／/api/nodes）共用，
    同一用户在三条路径上的 verdict 必须一致。"""
    if status == "revoked":
        return "已被吊销，.ovpn 不可下载（证书已进 CRL）"
    if status == "expired":
        return "证书已过期，.ovpn 不可下载"
    return None


def _snapshot_age_s(snap):
    """快照年龄（秒）：用 get_status 回执写入的 at（与 Worker cachedStatus
    的 age_s 同款）；无 at（从未收到 get_status 全量）时回 None。"""
    at = (snap or {}).get("at")
    if not isinstance(at, str) or not at:
        return None
    try:
        dt = datetime.fromisoformat(at)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())


def _remote_status_payload(node):
    """R11-P1-1：远程节点的 /api/status 回执。只读已存快照，绝不拿本机
    状态冒充。形状与本机 status() 同款（openvpn/sk5/egress），外加
    node/stale/age_s（与 Worker cachedStatus 同款，前端 loadStatus 已
    展示 stale 标记）；无快照时各段给空值、stale=true 并附 note，提示
    走 /api/cmd get_status 刷新。egress 的 via_sk5 判据与本机同款
    （R6-P1-1：enabled 且策略路由实测在位才认）；心跳形快照无
    policy_routing_active 时 via_sk5 保持 null、不编造。ovpn 段内的
    remote_ip 取快照 egress_ip（即该节点的实测出口），前端据此回填
    serverIp 输入框与 remote_warning，与本机同款。"""
    snap, _last_seen = _node_snapshot(node)
    age = _snapshot_age_s(snap)
    stale = age is None or age > 60
    ov = (snap or {}).get("openvpn") if isinstance((snap or {}).get("openvpn"), dict) else {}
    sk5 = (snap or {}).get("sk5") if isinstance((snap or {}).get("sk5"), dict) else {}
    if not ov and isinstance((snap or {}).get("openvpn_running"), bool):
        ov = {"running": bool(snap["openvpn_running"])}
    sk5_full = bool(sk5)
    if not sk5 and isinstance((snap or {}).get("sk5_enabled"), bool):
        sk5 = {"enabled": bool(snap["sk5_enabled"])}
    clients = ov.get("clients") if isinstance(ov.get("clients"), list) else []
    ovpn = {"running": bool(ov.get("running")), "online_users": len(clients),
            "unit_active": ov.get("unit_active"), "pid": ov.get("pid"),
            "error": ov.get("error")}
    for key in ("proto", "port", "subnet", "dns"):
        if ov.get(key) is not None:
            ovpn[key] = ov[key]
    egress_ip = (snap or {}).get("egress_ip")
    if not isinstance(egress_ip, str) or not egress_ip:
        egress_ip = None
    if egress_ip:
        ovpn["remote_ip"] = egress_ip
        if ip_is_private is not None:
            ovpn["remote_is_private"] = ip_is_private(egress_ip)
        ovpn["remote_warning"] = _remote_warning(egress_ip)
    sk5 = {k: v for k, v in sk5.items() if k != "password"}
    egress = {"ip": None, "latency_ms": None, "via_sk5": None, "error": None}
    if sk5_full and sk5.get("enabled") and sk5.get("policy_routing_active"):
        egress["ip"] = egress_ip
        egress["via_sk5"] = True
    elif sk5_full and sk5.get("enabled"):
        egress["via_sk5"] = False
        egress["error"] = "SK5 已启用但策略路由未生效，出口未经过 SK5"
    elif sk5_full:
        egress["ip"] = egress_ip
        egress["via_sk5"] = False
    out = {"ok": True, "node": node["name"], "openvpn": ovpn, "sk5": sk5,
           "egress": egress, "stale": stale,
           "age_s": (int(age) if age is not None else None)}
    if snap is None:
        out["note"] = "节点尚未上报状态：agent 首次 poll 后执行一次 get_status 即可"
    return out


def _remote_users_payload(node):
    """R11-P1-1：远程节点的 /api/openvpn/users 回执。读快照里的 users
    （agent get_status 上报），online 按快照 openvpn.clients 的 name
    集合算（与本机 _online_names() 同款）；无快照时空列表。"""
    snap, _last_seen = _node_snapshot(node)
    raw_users = (snap or {}).get("users")
    users = []
    if isinstance(raw_users, list):
        ov = (snap or {}).get("openvpn") if isinstance((snap or {}).get("openvpn"), dict) else {}
        clients = ov.get("clients") if isinstance(ov.get("clients"), list) else []
        online = {c.get("name") for c in clients
                  if isinstance(c, dict) and c.get("name")}
        for u in raw_users:
            if not isinstance(u, dict):
                continue
            name = u.get("name")
            users.append({"name": name, "status": u.get("status"),
                          "revoked": u.get("status") == "revoked",
                          "online": name in online,
                          "expires": u.get("expires"), "serial": u.get("serial"),
                          "legacy": bool(u.get("legacy"))})
    return {"ok": True, "node": node["name"], "users": users}


def _remote_sk5_payload(node):
    """R11-P1-1：远程节点的 /api/sk5 回执。读快照里的 sk5 段
    （agent get_status 上报），密码已由 _touch_node 的 _redact_dict
    脱敏，这里再防一手；无快照时空对象。"""
    snap, _last_seen = _node_snapshot(node)
    sk5 = (snap or {}).get("sk5") if isinstance((snap or {}).get("sk5"), dict) else {}
    sk5 = {k: v for k, v in sk5.items() if k != "password"}
    return {"ok": True, "node": node["name"], "sk5": sk5}


def _find_node_by_token(token):
    conn = _db()
    row = conn.execute(
        "SELECT name, token_hash, panel_url, created_at, last_seen,"
        " last_status FROM nodes WHERE token_hash = ?",
        (_hash_token(token),)).fetchone()
    conn.close()
    return dict(row) if row else None


def _touch_node(name, status):
    """更新节点 last_seen / last_status（状态快照先脱敏）。
    R11-P1-1：快照是合并写——心跳只带 version/hostname/openvpn_running/
    sk5_enabled，get_status 回执才带 openvpn/users/sk5 全量；直接覆盖
    会让全量快照在下一次 poll（≤5 秒）就被心跳冲掉，远程读永远拿不
    到全量。合并时新值按 key 覆盖旧值（心跳键与全量键不重名）；get_status
    回执另带 at=回执时刻（见 agent_report），供远程读算 stale。"""
    try:
        conn = _db()
        row = conn.execute(
            "SELECT last_status FROM nodes WHERE name = ?", (name,)).fetchone()
        old = {}
        if row and row["last_status"]:
            try:
                old = json.loads(row["last_status"])
            except ValueError:
                old = {}
        if not isinstance(old, dict):
            old = {}
        merged = dict(old)
        merged.update(_redact_dict(status or {}))
        conn.execute(
            "UPDATE nodes SET last_seen = ?, last_status = ? WHERE name = ?",
            (_utcnow_iso(),
             json.dumps(merged, ensure_ascii=False),
             name))
        conn.commit()
        conn.close()
    except Exception:  # noqa: BLE001 - 心跳更新失败不阻塞 poll
        pass


def _agent_auth():
    """鉴权 agent 请求，返回 (node_dict, err_response)。
    接受 Authorization: Bearer <token> 或 body.node_token；
    两者都在且不一致 -> 401（防 token 混用冒领）。"""
    auth = request.headers.get("Authorization", "") or ""
    header_token = None
    if auth.startswith("Bearer "):
        header_token = auth[7:].strip() or None
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    body_token = data.get("node_token")
    if body_token is not None:
        body_token = str(body_token)
    if header_token and body_token and not secrets.compare_digest(
            header_token, body_token):
        return None, (jsonify({"ok": False, "error": "token 不一致"}), 401)
    token = header_token or body_token
    if not token:
        return None, (jsonify({"ok": False, "error": "缺少节点 token"}), 401)
    node = _find_node_by_token(token)
    if not node:
        return None, (jsonify({"ok": False, "error": "节点 token 无效"}), 401)
    claimed_name = data.get("node_name")
    if claimed_name and str(claimed_name) != node["name"]:
        return None, (jsonify({"ok": False, "error": "token 与节点名不匹配"}), 401)
    return node, None


def _check_panel_claim(node, data):
    """FLMX 认领守卫：节点注册时绑定的 panel_url 与 agent 配置里的
    panel_url 必须逐字相等（仅去尾斜杠），否则拒绝认领——防别的面板
    拿一个有效 token 就把节点接管走。
    注册时填的 panel_url 必须与给 agent 的 --panel-url 逐字一致。
    agent 未上报 panel_url（旧版 agent）时放行，但 poll 响应里带
    panel_url_unverified 提示升级 agent。"""
    stored = (node.get("panel_url") or "").rstrip("/")
    claimed = data.get("panel_url")
    if claimed is not None:
        claimed = str(claimed).rstrip("/")
    if stored and claimed and claimed != stored:
        return False, ("panel_url 不匹配：节点注册于 %s，agent 配置为 %s，"
                       "拒绝认领" % (stored, claimed))
    if stored and not claimed:
        return True, "unverified"
    return True, "ok"


def _require_module(name):
    if name in _IMPORT_ERRORS:
        return jsonify({"ok": False, "error": "module_missing",
                        "module": name, "detail": _IMPORT_ERRORS[name]}), 503
    return None


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("admin"):
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        # P1-7：改密后 session_version +1，全部旧会话在此失效。
        # 升级前建的会话无 "v" 字段，视为已作废（须重新登录一次）。
        if session.get("v") != _session_version():
            session.clear()
            return jsonify({"ok": False, "error": "session_revoked"}), 401
        return fn(*args, **kwargs)
    return wrapper


def _json_body():
    if not request.is_json:
        return {}, "请求体须为 JSON"
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}, "请求体须为 JSON 对象"
    return data, None


def _valid_port(value):
    # R12-P1-2：bool 是 int 的子类，isinstance(True, int) 为真——
    # port=True 曾通过本校验并把字面 "port True" 写进 server.conf，
    # 随后一切渲染 500。type() is int 只接受真整数。
    return type(value) is int and 1 <= value <= 65535


def _coerce_bool(value, key):
    """R12-P2-1：把一个 JSON 布尔开关输入规整为真布尔。

    只接受真布尔与 0/1 整数（0->False、1->True：无反向可能，
    R12 探针 X10/X11 明确钉死该语义）；其余一律拒绝——
    bool("false") 是 True，字符串 "false" 曾让全族开关反向执行。
    返回 (value, None)，或 (None, err)。"""
    if isinstance(value, bool):
        return value, None
    if isinstance(value, int) and value in (0, 1):
        return bool(value), None
    return None, "%s 须为 JSON 布尔值（true/false）或 0/1，收到 %s" % (
        key, type(value).__name__)


def _strict_bool(data, key, default=False):
    """R12-P2-1：读 data 里一个布尔开关。缺键取 default（旧缺省语义），
    在键时须为真布尔或 0/1，否则返回 (None, err)。"""
    if key not in data:
        return default, None
    return _coerce_bool(data[key], key)


def _toggle_value(data, key, fallback=None, default=False):
    """R12-P2-2：读 key 优先、回落 fallback 键，两者都缺时 default。
    值须为真布尔或 0/1，否则返回 (None, err)。"""
    if key in data:
        return _coerce_bool(data[key], key)
    if fallback is not None and fallback in data:
        return _coerce_bool(data[fallback], fallback)
    return default, None


def _safe_int(value):
    """把 retries 这类手改队列字段规整为 int；不可规整时回 None
    （R12-P1-1/P2-7：retries="abc" 曾让 cmd_get 的 int() 抛
    ValueError 致 500）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            try:
                return int(text)
            except ValueError:
                return None
    return None


def _parse_server_conf():
    """从渲染好的 server.conf 读 proto/port,读不到返回环境默认值."""
    proto = os.environ.get("OPENVPN_PROTO", "udp")
    port = int(os.environ.get("OPENVPN_PORT", "1194"))
    try:
        for line in (SERVER_DIR / "server.conf").read_text(
                encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("proto "):
                proto = line.split(None, 1)[1].strip()
            elif line.startswith("port "):
                port = int(line.split(None, 1)[1].strip())
    except (OSError, ValueError):
        pass
    return proto, port


# 观察-1：.ovpn 的 remote 地址（对外地址）。默认自动探测公网 IP；
# 管理员也可在面板上显式填一个（域名或 IP），存在
# DATA_DIR/server.json；留空即恢复自动探测。Cloudflare 模式的
# Worker 兼容层目前只转发 port/proto/name（见 cloudflare/README），
# 显式地址在该模式下暂不起作用，agent 侧靠 core 的公网探测决定
# remote——该限制写在面板 README 里，不静默假装生效。
SERVER_SETTINGS_FILE = os.path.join(DATA_DIR, "server.json")
_HOST_RE = re.compile(r"^[A-Za-z0-9._:-]{1,253}$")


def _valid_server_ip(value):
    """对外地址合法性：IP 字面量或主机名，不含空白与 shell 元字符。"""
    if not isinstance(value, str):
        return False
    value = value.strip()
    if not value or any(c in value for c in " \t\"';&|<>$`\\"):
        return False
    try:
        import ipaddress as _ip
        _ip.ip_address(value)
        return True
    except ValueError:
        pass
    return bool(_HOST_RE.match(value)) and ".." not in value


def _load_server_settings():
    try:
        with open(SERVER_SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_server_settings(data):
    tmp = SERVER_SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, SERVER_SETTINGS_FILE)


def _stored_server_ip():
    ip = _load_server_settings().get("server_ip")
    return ip.strip() if isinstance(ip, str) and ip.strip() else None


def _remote_warning(ip):
    """remote 是内网/回环地址时，站外客户端连不上——必须明示，
    不许静默发一个连不上的 .ovpn。"""
    if ip_is_private is not None and ip_is_private(ip):
        return ("当前 .ovpn 的 remote 为内网地址 %s，站外客户端连不上："
                "请在上方填公网 IP/域名，或点“自动探测公网 IP”" % ip)
    return None


def _outward_ip():
    """生成 .ovpn 的 remote 地址：显式设置 > 环境变量 > 公网探测 >
    局域网地址。观察-1：旧顺序把局域网地址放第一，NAT/云主机上
    每个 .ovpn 的 remote 都是内网 IP，站外根本连不上。"""
    ip = _stored_server_ip() or os.environ.get("OPENVPN_SERVER_IP")
    if ip:
        return ip
    if detect_public_ip is not None:
        try:
            detected = detect_public_ip()
        except Exception:  # noqa: BLE001 - 探测失败即回落，不阻塞
            detected = None
        if detected:
            return detected
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
        finally:
            sock.close()
    except OSError:
        return "127.0.0.1"


def _rebuild_user_ovpn(name):
    """core 没有 get_user_ovpn(),故用已签发证书/私钥重建 .ovpn.

    读取 pki/ca.crt、pki/issued/<name>.crt、pki/private/<name>.key、
    server_dir/ta.key,再调 core.build_client_config() 渲染,与
    create_user() 当时生成的文本一致(除 remote 解析时点外).
    """
    pki = CA_DIR / "pki"
    blobs = {}
    for label, path in (
            ("ca", pki / "ca.crt"),
            ("cert", pki / "issued" / ("%s.crt" % name)),
            ("key", pki / "private" / ("%s.key" % name)),
            ("ta_key", SERVER_DIR / "ta.key")):
        try:
            blobs[label] = path.read_text(encoding="utf-8")
        except OSError:
            blobs[label] = None
    if blobs["ta_key"] is None:
        try:
            blobs["ta_key"] = (pki / "ta.key").read_text(encoding="utf-8")
        except OSError:
            blobs["ta_key"] = None
    missing = [k for k, v in blobs.items() if not v]
    if missing:
        raise FileNotFoundError("重建 .ovpn 缺少文件: %s" % ", ".join(missing))
    proto, port = _parse_server_conf()
    return build_client_config(name, blobs["ca"], blobs["cert"], blobs["key"],
                               blobs["ta_key"], _outward_ip(), proto, port)


def _online_names():
    try:
        status = server_status()
    except Exception:  # noqa: BLE001 - 状态源失败时在线集为空,不阻塞列表
        return set()
    clients = status.get("clients") if isinstance(status, dict) else None
    if not isinstance(clients, list):
        return set()
    return {c.get("name") for c in clients
            if isinstance(c, dict) and c.get("name")}


# ---------------- 页面与认证 ----------------
@app.route("/")
def index():
    return send_from_directory(
        os.path.join(BASE_DIR, "templates"), "index.html")


@app.route("/api/login", methods=["POST"])
def login():
    data, err = _json_body()
    if err:
        return jsonify({"ok": False, "error": err}), 400
    ip = request.remote_addr or "unknown"
    locked_until = _login_locked_until(ip)
    if locked_until:
        retry = int(locked_until - time.time()) + 1
        _audit("login_locked", actor="ip:" + ip, result="denied",
               detail="retry_after_s=%d" % retry)
        resp = jsonify({"ok": False, "error": "登录失败过多，已锁定，请 %d 秒后再试" % retry,
                        "retry_after_s": retry})
        resp.headers["Retry-After"] = str(retry)
        return resp, 429
    password = data.get("password", "")
    conn = _db()
    row = conn.execute("SELECT password_hash, session_version FROM admin"
                       " WHERE id = 1").fetchone()
    if not row or not _check_password(str(password), row["password_hash"]):
        conn.close()
        _record_login_failure(ip)
        _audit("login", actor="ip:" + ip, result="fail", detail="密码错误")
        return jsonify({"ok": False, "error": "密码错误"}), 401
    stored = row["password_hash"]
    version = int(row["session_version"] or 1)
    # P2-5：旧 "salt:digest" 哈希登录成功即透明迁移到 bcrypt，
    # 迁移后旧哈希作废（下次登录只认 bcrypt）。
    if _bcrypt is not None and not stored.startswith("$2"):
        try:
            conn.execute("UPDATE admin SET password_hash = ? WHERE id = 1",
                         (_hash_password(str(password)),))
            conn.commit()
        except Exception:  # noqa: BLE001 - R9-P2-2 同族：磁盘满时迁移失败不阻塞登录，旧哈希仍可用
            pass
    conn.close()
    _clear_login_failures(ip)
    session["admin"] = True
    session["v"] = version
    session.permanent = True
    _audit("login", actor="admin", result="ok", detail="ip=%s" % ip)
    return jsonify({"ok": True})


@app.route("/api/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    _audit("logout", actor="admin", result="ok")
    return jsonify({"ok": True})


@app.route("/api/change-password", methods=["POST"])
@login_required
def change_password():
    """P1-7：管理员改密。校验旧密码与新密码强度；成功后
    session_version +1，全部旧会话（含本次）立即作废，须重新登录。
    初始密码文件（/etc/openvpn-sk5-panel/admin.pass，若存在）同步
    更新为新密码，否则安装健康门禁会拿旧密码登录失败。"""
    data, err = _json_body()
    if err:
        return jsonify({"ok": False, "error": err}), 400
    old = str(data.get("old_password", ""))
    new = str(data.get("new_password", ""))
    conn = _db()
    row = conn.execute("SELECT password_hash FROM admin WHERE id = 1").fetchone()
    if not row or not _check_password(old, row["password_hash"]):
        conn.close()
        _audit("change_password", result="fail", detail="旧密码错误")
        return jsonify({"ok": False, "error": "旧密码错误"}), 401
    ok, msg = _validate_new_password(old, new)
    if not ok:
        conn.close()
        return jsonify({"ok": False, "error": msg}), 400
    try:
        new_hash = _hash_password(new)
    except ValueError:
        # R31-P2-2 defense in depth: _validate_new_password already
        # caps UTF-8 at 72 bytes, but a future bcrypt behavior change
        # must not turn this into an unhandled 500 again.
        conn.close()
        return jsonify({"ok": False, "error": _PASSWORD_TOO_LONG}), 400
    conn.execute("UPDATE admin SET password_hash = ?,"
                 " session_version = session_version + 1 WHERE id = 1",
                 (new_hash,))
    conn.commit()
    conn.close()
    for path in (ADMIN_PASS_PATH, ADMIN_PASS_FALLBACK):
        if os.path.exists(path):
            try:
                with open(path, "w") as f:
                    f.write(new + "\n")
                os.chmod(path, 0o600)
            except OSError:
                pass
    session.clear()
    _audit("change_password", result="ok",
           detail="全部旧会话已作废，须重新登录")
    return jsonify({"ok": True,
                    "note": "密码已修改，全部旧会话已作废，请重新登录"})


@app.route("/api/me", methods=["GET"])
def me():
    return jsonify({"ok": True, "admin": bool(session.get("admin"))})


# ---------------- 总状态 ----------------
# P1-1：/api/status 曾做两次串行 egress 探针（sk5_get_status() 内部
# 一次 + status() 又调一次 current_egress_ip()），SK5 静默时 20 秒。
# 修法：SK5 启用时直接复用 get_status() 已探到的 egress_ip；直连
# 探针加 10 秒缓存（前端每 15 秒轮询一次，缓存不影响新鲜度）。
_SK5_STATUS_CACHE = {"at": 0.0, "sk5": None}
_SK5_STATUS_CACHE_TTL = 10.0
# R7-BUG-3: serialises every SK5 *mutation* in this process (save /
# enable / disable / fail-open / udp-over-tcp). The effective-state
# check inside set_sk5 only covers serial calls: two concurrent
# enables both read enabled=false before either writes, and both then
# run the full render + daemon restart. Holding this lock across the
# read-check-apply sequence makes the whole mutation atomic in-process.
# Why a lock and not CAS: a compare-and-swap re-check before the
# render still leaves a window between the re-read and the apply; the
# lock closes it. Why here and not in the egress script: the script
# already serialises its own calls with flock, but the race is in the
# panel's read-then-mutate decision, which the script cannot see.
# Scope: mutation routes only. GET /api/status and GET /api/sk5 read
# through _cached_sk5_status / sk5_get_status without this lock, so
# status reads are never serialised behind a mutation. Lock ordering:
# this lock is outermost; never acquire it while holding
# _SK5_STATUS_LOCK, and never call _cached_sk5_status() while holding
# it (use the raw sk5_get_status() inside the lock instead).
_SK5_MUTATE_LOCK = threading.Lock()
_SK5_STATUS_LOCK = threading.Lock()
_EGRESS_CACHE = {"at": 0.0, "ip": None, "error": None}
_EGRESS_CACHE_TTL = 10.0
_EGRESS_CACHE_LOCK = threading.Lock()


def _cached_sk5_status():
    """10 秒内复用上一次 get_status() 结果（含它内部那次探针）。
    注意：缓存时间戳取探针完成时——取开始时的话，一次 10 秒探针
    跑完缓存就已过期，等于没缓存。"""
    with _SK5_STATUS_LOCK:
        now = time.time()
        if (_SK5_STATUS_CACHE["sk5"] is not None
                and now - _SK5_STATUS_CACHE["at"] < _SK5_STATUS_CACHE_TTL):
            return dict(_SK5_STATUS_CACHE["sk5"])
        sk5 = dict(sk5_get_status())
        _SK5_STATUS_CACHE.update({"at": time.time(), "sk5": sk5})
        return dict(sk5)


def _probe_egress_cached():
    """直连出口探针（SK5 未启用时用），10 秒缓存（时间戳同上，
    取探针完成时）。"""
    with _EGRESS_CACHE_LOCK:
        now = time.time()
        if now - _EGRESS_CACHE["at"] < _EGRESS_CACHE_TTL:
            return _EGRESS_CACHE["ip"], _EGRESS_CACHE["error"]
        try:
            ip = current_egress_ip()
            err = None
        except Exception as exc:  # noqa: BLE001
            ip, err = None, str(exc)
        _EGRESS_CACHE.update({"at": time.time(), "ip": ip, "error": err})
        return ip, err


@app.route("/api/status", methods=["GET"])
@login_required
def status():
    # R11-P1-1：指名节点时读该节点的已存快照，绝不拿本机状态冒充。
    node, err = _resolve_compat_node()
    if err:
        return err
    if node is not None:
        return jsonify(_remote_status_payload(node))
    ovpn = {"running": False, "online_users": 0,
            "subnet": FIXED_SUBNET, "dns": FIXED_DNS, "error": None}
    if server_status is not None:
        try:
            raw = server_status()
            clients = raw.get("clients") if isinstance(raw, dict) else None
            proto, port = _parse_server_conf()
            remote_ip = _outward_ip()
            ovpn.update({"running": bool(raw.get("running")),
                         "online_users": len(clients)
                         if isinstance(clients, list) else 0,
                         "unit_active": raw.get("unit_active"),
                         "pid": raw.get("pid"),
                         "proto": proto, "port": port,
                         "remote_ip": remote_ip,
                         "remote_is_private": bool(
                             ip_is_private(remote_ip))
                         if ip_is_private is not None else None,
                         "remote_warning": _remote_warning(remote_ip),
                         "error": raw.get("error"),
                         "detail": raw})
        except Exception as exc:  # noqa: BLE001 - 状态接口不因单源失败而挂
            ovpn["error"] = str(exc)
    else:
        ovpn["error"] = "openvpn_manager 未落盘: %s" % _IMPORT_ERRORS.get(
            "openvpn_manager", "")
    sk5 = {"enabled": False, "error": None}
    if sk5_get_status is not None:
        try:
            # 带 10 秒缓存：get_status() 内部已探一次 egress，
            # 状态轮询不再另起探针。
            sk5 = _cached_sk5_status()
        except Exception as exc:  # noqa: BLE001
            sk5["error"] = str(exc)
    else:
        sk5["error"] = "sk5_manager 未落盘: %s" % _IMPORT_ERRORS.get(
            "sk5_manager", "")
    egress = {"ip": None, "latency_ms": None, "via_sk5": None, "error": None}
    if current_egress_ip is not None:
        # 状态轮询只取 IP,不跑全量 test(慢);延迟见 POST /api/sk5/test
        if sk5.get("enabled") and sk5.get("policy_routing_active"):
            # SK5 已启用且策略路由实测在位：复用 get_status() 那次探针
            # 的结果，不再探第二次。探针 IP 取不到时 ip=None 但 via_sk5
            # 仍为 true——流量确实进链后黑洞（kill-switch 工作态，
            # 见 via_sk5 探针 case D）。
            egress["ip"] = sk5.get("egress_ip")
            egress["via_sk5"] = True
        elif sk5.get("enabled"):
            # R6-P1-1: enabled 但策略路由缺失时，VPN 流量根本不走链，
            # 绝不能复用探针 IP 宣称经 SK5。旧分支只看 "egress_ip"
            # in sk5——get_status() 在 enabled 时恒写该键，S 路的
            # else 分支在启用路径上永远不可达，面板谎称 via_sk5。
            # via_sk5 的唯一判据是实测的 policy_routing_active
            # (ip rule + table 100 default via tun1)。
            egress["ip"] = None
            egress["via_sk5"] = False
            egress["error"] = "SK5 已启用但策略路由未生效，出口未经过 SK5"
        else:
            # SK5 未启用：出口是直连探针 IP，via_sk5 恒为 False。
            egress["ip"], egress["error"] = _probe_egress_cached()
            egress["via_sk5"] = False
    return jsonify({
        "ok": True,
        "openvpn": ovpn,
        "sk5": sk5,
        "egress": egress,
        "modules_missing": sorted(_IMPORT_ERRORS),
    })


# ---------------- OpenVPN ----------------
@app.route("/api/openvpn/server", methods=["POST"])
@login_required
def ovpn_server():
    data, err = _json_body()
    if err:
        return jsonify({"ok": False, "error": err}), 400
    # R11-P1-1：先解析节点——远程节点不依赖本机 core（模块检查只
    # 在本机分支做）；ghost 节点在端口校验之前 404（与 Worker
    # resolveNode 先行的顺序同款）。
    node, err = _resolve_compat_node(data)
    if err:
        return err
    port = data.get("port")
    proto = str(data.get("proto", "udp")).lower()
    if port is None:
        port = 1194 if proto == "udp" else 443
    if not _valid_port(port):
        return jsonify({"ok": False, "error": "port 须为 1-65535 的整数"}), 400
    if proto not in ("udp", "tcp"):
        return jsonify({"ok": False, "error": "proto 只能为 udp 或 tcp"}), 400
    # R2-BUG-14: allow_port_change 必须透传给 core.render_server_conf。
    # 旧代码只传 proto/port，把该字段丢在路由层——core 拒绝改口后
    # 报错指引用户传 allow_port_change，但 API 上根本走不通。
    # R12-P2-1：须为真布尔或 0/1；字符串 "false" 曾被 bool() 变成 True
    # 而绕过 P01 冻结真移端口。
    allow_port_change, err = _strict_bool(data, "allow_port_change", False)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    if node is not None:
        # server_ip 不入队：它是面板本机的对外地址设置，远程节点
        # 的 .ovpn remote 由 agent 侧按自身出口解析（远程状态回执
        # 已把该出口作为 ovpn.remote_ip 报给前端表单）。
        return _enqueue_compat(node["name"], "create_server",
                               {"proto": proto, "port": port,
                                "allow_port_change": allow_port_change},
                               "openvpn_server_config")
    missing = _require_module("openvpn_manager")
    if missing:
        return missing
    # 观察-1：对外地址（.ovpn 的 remote）。显式传来即保存；传空串
    # 即清除保存值、恢复自动探测；不传则保持现有值。
    server_ip = data.get("server_ip", None)
    settings = _load_server_settings()
    if server_ip is not None:
        server_ip = str(server_ip).strip()
        if server_ip and not _valid_server_ip(server_ip):
            return jsonify({"ok": False,
                            "error": "server_ip 不合法：须为 IP 或主机名"}), 400
        if server_ip:
            settings["server_ip"] = server_ip
        else:
            settings.pop("server_ip", None)
        try:
            _save_server_settings(settings)
        except OSError as exc:
            return jsonify({"ok": False,
                            "error": "保存对外地址失败：%s" % exc}), 500
    try:
        conf_path = render_server_conf(proto=proto, port=port,
                                       allow_port_change=allow_port_change)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500
    remote_ip = _outward_ip()
    _audit("openvpn_server_config", result="ok",
           detail="proto=%s port=%d allow_port_change=%s server_ip=%s"
                  % (proto, port, allow_port_change, remote_ip))
    return jsonify({"ok": True, "server": {
        "proto": proto, "port": port, "conf_path": str(conf_path),
        "subnet": FIXED_SUBNET, "dns": FIXED_DNS,
        "server_ip": remote_ip,
        "remote_warning": _remote_warning(remote_ip),
        "note": "子网/DNS 由 core 固定为 %s / %s,改配置后需重启服务才生效"
                % (FIXED_SUBNET, FIXED_DNS)}})


@app.route("/api/openvpn/public-ip", methods=["GET"])
@login_required
def ovpn_public_ip():
    """探测本机的公网 IP（供“对外地址”字段自动填充）。探测不到时
    明确报错，不返回局域网地址冒充。Cloudflare 模式无此端点
    （Worker 不知道中转机的出口 IP），前端据此隐藏探测按钮。
    R11-P1-1：指名远程节点时不探本机，读该节点的已存快照出口 IP；
    快照无出口 IP 时诚实 502，绝不拿本机 IP 冒充。"""
    # R11-P1-1：withNode 对本路由同样追加 ?node=，须先解析。
    node, err = _resolve_compat_node()
    if err:
        return err
    if node is not None:
        snap, _last_seen = _node_snapshot(node)
        ip = (snap or {}).get("egress_ip")
        if not isinstance(ip, str) or not ip:
            return jsonify({"ok": False,
                            "error": "节点尚未上报出口 IP：先让 agent "
                                     "上报一次 get_status"}), 502
        return jsonify({"ok": True, "ip": ip})
    if detect_public_ip is None:
        return jsonify({"ok": False,
                        "error": "openvpn_manager 未落盘"}), 503
    try:
        ip = detect_public_ip()
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500
    if not ip:
        return jsonify({"ok": False,
                        "error": "探测不到公网 IP（出口无公网地址或探测服务不可达）"}), 502
    return jsonify({"ok": True, "ip": ip})


@app.route("/api/openvpn/start", methods=["POST"])
@login_required
def ovpn_start():
    # R11-P1-1：指名远程节点时入队，不碰本机服务。
    node, err = _resolve_compat_node()
    if err:
        return err
    if node is not None:
        return _enqueue_compat(node["name"], "start_openvpn", {},
                               "openvpn_start")
    missing = _require_module("openvpn_manager")
    if missing:
        return missing
    try:
        result = start_server()
        _audit("openvpn_start", result="ok")
        return jsonify({"ok": True, "result": result})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/openvpn/stop", methods=["POST"])
@login_required
def ovpn_stop():
    # R11-P1-1：指名远程节点时入队，不碰本机服务。
    node, err = _resolve_compat_node()
    if err:
        return err
    if node is not None:
        return _enqueue_compat(node["name"], "stop_openvpn", {},
                               "openvpn_stop")
    missing = _require_module("openvpn_manager")
    if missing:
        return missing
    try:
        result = stop_server()
        _audit("openvpn_stop", result="ok")
        return jsonify({"ok": True, "result": result})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/openvpn/restart", methods=["POST"])
@login_required
def ovpn_restart():
    # R11-P1-1：指名远程节点时入队，不碰本机服务。
    node, err = _resolve_compat_node()
    if err:
        return err
    if node is not None:
        return _enqueue_compat(node["name"], "restart_openvpn", {},
                               "openvpn_restart")
    missing = _require_module("openvpn_manager")
    if missing:
        return missing
    try:
        result = restart_server()
        _audit("openvpn_restart", result="ok")
        return jsonify({"ok": True, "result": result})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/openvpn/init-pki", methods=["POST"])
@login_required
def ovpn_init_pki():
    """重建 CA（R7-P2-9）：面板入口，走 /api/cmd 命令链入队 agent 执行。

    与 live-verify-R5 §14.3 的手写路径同一条链：入队 init_pki 后
    agent 侧 init_pki(force=True) + build_server_cert()，返回 202 +
    cmd_id，前端用 apiWait() 轮询 /api/cmd/:id 等 done/failed。
    force 与 confirm 须同时为 true：force=true 销毁现有 CA，全部
    已签发用户证书立即失效；缺一律 400 并明示后果，绝不静默执行。
    node 取 body.node 或 ?node=；未传时单节点自动用唯一节点（与
    前端“单节点留空”约定一致），多节点未指定则 400。
    """
    data, err = _json_body()
    if err:
        return jsonify({"ok": False, "error": err}), 400
    # 先验破坏性意图（与 /api/cmd 先验 action 的顺序一致）：缺
    # force/confirm 一律 400，不走到节点判定。
    if data.get("force") is not True:
        return jsonify({"ok": False,
                        "error": "重建 CA 须显式传 force=true：将销毁现有 CA，"
                                 "全部已签发用户证书立即失效"}), 400
    if data.get("confirm") is not True:
        return jsonify({"ok": False,
                        "error": "重建 CA 须并传 confirm=true 二次确认："
                                 "全部已签发用户证书将失效，须重建用户并重新"
                                 "下载 .ovpn"}), 400
    node_name = str(data.get("node") or request.args.get("node") or "").strip()
    if not node_name:
        conn = _db()
        rows = conn.execute("SELECT name FROM nodes ORDER BY name").fetchall()
        conn.close()
        if len(rows) == 1:
            node_name = rows[0]["name"]
    if not node_name:
        return jsonify({"ok": False,
                        "error": "须指定 node（多节点时传 node 字段或 ?node= 参数；"
                                 "单节点时面板自动用唯一节点）"}), 400
    # R11-P1-1：存在性判定与兼容层共用 _lookup_node（同款 404 文案）。
    _node, err = _lookup_node(node_name)
    if err:
        return err
    cmd = _enqueue_command(node_name, "init_pki",
                           {"force": True, "confirm": True})
    _audit("openvpn_init_pki", node=node_name, result="ok",
           detail="cmd_id=%s force=true confirm=true" % cmd["id"])
    return jsonify({"ok": True, "cmd_id": cmd["id"], "node": node_name,
                    "action": "init_pki", "status": "queued",
                    "queued": True}), 202


@app.route("/api/openvpn/users", methods=["GET"])
@login_required
def ovpn_users_list():
    # R11-P1-1：指名远程节点时读快照用户列表，不读本机 index.txt。
    node, err = _resolve_compat_node()
    if err:
        return err
    if node is not None:
        return jsonify(_remote_users_payload(node))
    missing = _require_module("openvpn_manager")
    if missing:
        return missing
    try:
        online = _online_names()
        users = []
        for u in list_users():
            users.append({"name": u.get("name"), "status": u.get("status"),
                          "revoked": u.get("status") == "revoked",
                          "online": u.get("name") in online,
                          "expires": u.get("expires"),
                          "serial": u.get("serial"),
                          # R2-P1-3: pre-BUG-7 cert (CN=OpenVPN-CA);
                          # frontend shows an "旧证书" badge for it.
                          "legacy": bool(u.get("legacy"))})
        return jsonify({"ok": True, "users": users})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/openvpn/users", methods=["POST"])
@login_required
def ovpn_users_create():
    data, err = _json_body()
    if err:
        return jsonify({"ok": False, "error": err}), 400
    # R11-P1-1：先解析节点（ghost 404 在名字校验之前，与 Worker
    # resolveNode 先行的顺序同款）；模块检查仍在 validate_username
    # 之前（该函数随 openvpn_manager 导入，缺模块时为 None）。
    node, err = _resolve_compat_node(data)
    if err:
        return err
    missing = _require_module("openvpn_manager")
    if missing:
        return missing
    name = str(data.get("name", "")).strip()
    try:
        validate_username(name)
    except Exception as exc:  # noqa: BLE001 - core 规则 [a-zA-Z0-9_-]{1,32}
        return jsonify({"ok": False, "error": str(exc)}), 400
    if node is not None:
        # 远程只入队 {name}：agent 侧按自身出口解析 .ovpn remote，
        # 不传面板本机的 server_ip。
        return _enqueue_compat(node["name"], "create_user", {"name": name},
                               "openvpn_user_create")
    try:
        # 观察-1：建用户时把已保存的对外地址传给 core，否则新签发的
        # .ovpn 仍按旧逻辑解析 remote（内网地址）。
        create_user(name, server_ip=_stored_server_ip())
        _audit("openvpn_user_create", result="ok", detail="name=%s" % name)
    except UserAlreadyExistsError as exc:
        # R5-P2-1: predictable client error, not a server failure --
        # 409 (the route is only reached after _require_module, so
        # the subclass name is bound here).
        return jsonify({"ok": False, "error": str(exc)}), 409
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "user": {"name": name, "status": "valid"},
                    "ovpn_url": "/api/openvpn/users/%s/ovpn" % name})


@app.route("/api/openvpn/users/<name>", methods=["DELETE"])
@login_required
def ovpn_users_revoke(name):
    # R11-P1-1：先解析节点（ghost 404 在名字校验之前）；模块检查
    # 仍在 validate_username 之前（见 ovpn_users_create）。
    node, err = _resolve_compat_node()
    if err:
        return err
    missing = _require_module("openvpn_manager")
    if missing:
        return missing
    try:
        validate_username(name)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 400
    if node is not None:
        return _enqueue_compat(node["name"], "revoke_user", {"name": name},
                               "openvpn_user_revoke")
    try:
        result = revoke_user(name)
        _audit("openvpn_user_revoke", result="ok", detail="name=%s" % name)
    except UserNotFoundError as exc:
        # R5-P2-1: predictable client error, not a server failure.
        return jsonify({"ok": False, "error": str(exc)}), 404
    except UserAlreadyRevokedError as exc:
        # R5-P2-1, same family: the resource exists but its state
        # forbids the operation -- 409, not 500.
        return jsonify({"ok": False, "error": str(exc)}), 409
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify({"ok": True, "result": result, "needs_restart": True,
                    "note": "OpenVPN 只在启动时读 CRL,吊销后须重启服务才对新连接生效"})


@app.route("/api/openvpn/users/<name>/ovpn", methods=["GET"])
@login_required
def ovpn_users_download(name):
    # R11-P1-1：先解析节点（ghost 404 在名字校验之前）；模块检查
    # 仍在 validate_username 之前（见 ovpn_users_create）。
    node, err = _resolve_compat_node()
    if err:
        return err
    missing = _require_module("openvpn_manager")
    if missing:
        return missing
    try:
        validate_username(name)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 400
    if node is not None:
        # 远程读队列里的 .ovpn 回执（与 /api/nodes/<node>/users/<user>/ovpn
        # 同一存处），已吊销按快照用户状态 403，绝不静默下发本机文件。
        # 未指名时走本机文件（今天的行为；下载链接是纯浏览器 href、
        # 不带 ?node=，多节点下前端须把 ?node= 补进 href 才能下到远程
        # 节点的 .ovpn——前端跟进项，见本轮报告）。
        users = _snapshot_users(node)
        user = users.get(name)
        reason = _download_block_reason(
            user.get("status") if isinstance(user, dict) else None)
        if reason:
            return jsonify({"ok": False,
                            "error": "用户 %s %s" % (name, reason)}), 403
        with _QUEUE_LOCK:
            state = _load_queue()
            rec = state["ovpn"].get("%s:%s" % (node["name"], name))
        content = rec.get("ovpn") if isinstance(rec, dict) else None
        if not content or not str(content).strip():
            return jsonify({"ok": False,
                            "error": "该用户 .ovpn 尚未生成/上报：先建用户，"
                                     "等 agent 回执后再下载"}), 404
        return app.response_class(
            content, mimetype="application/x-openvpn-profile",
            headers={"Content-Disposition":
                     'attachment; filename="%s.ovpn"' % name})
    # P2-10／R13-P2-3：先查用户状态——已吊销／已过期用户拒绝下载
    # （证书已进 CRL 或已过期，下载回去也连不上），不存在的用户报 404。
    try:
        users = {u.get("name"): u for u in list_users()}
    except Exception:  # noqa: BLE001 - 状态源失败时不阻塞下载
        users = {}
    user = users.get(name)
    if user is None:
        return jsonify({"ok": False, "error": "用户不存在：%s" % name}), 404
    reason = _download_block_reason(user.get("status"))
    if reason:
        return jsonify({"ok": False,
                        "error": "用户 %s %s" % (name, reason)}), 403
    try:
        content = _rebuild_user_ovpn(name)
    except FileNotFoundError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500
    if not content.strip():
        return jsonify({"ok": False, "error": "未取到该用户的 .ovpn 内容"}), 404
    return app.response_class(
        content, mimetype="application/x-openvpn-profile",
        headers={"Content-Disposition":
                 'attachment; filename="%s.ovpn"' % name})


# ---------------- SK5 ----------------
def _stored_sk5_password():
    """读已存 SK5 配置里的密码（P0-4：保存时空密码即保留）。
    读不到（未配置/无权限）返回 ""，调用方按无密码处理。"""
    if SK5_CONFIG_FILE is None:
        return ""
    try:
        cfg = json.loads(SK5_CONFIG_FILE.read_text(encoding="utf-8"))
        return str(cfg.get("password") or "")
    except (OSError, ValueError):
        return ""


@app.route("/api/sk5", methods=["GET"])
@login_required
def sk5_get():
    # R11-P1-1：指名远程节点时读快照 SK5 段，不读本机配置。
    node, err = _resolve_compat_node()
    if err:
        return err
    if node is not None:
        return jsonify(_remote_sk5_payload(node))
    missing = _require_module("sk5_manager")
    if missing:
        return missing
    try:
        return jsonify({"ok": True, "sk5": sk5_get_status()})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500


def _sk5_save_remote(node, data):
    """R11-P1-1：远程节点的 SK5 保存。只做面板侧校验（与本机同款
    400 文案），不读本机存量、不写本机配置，全部经 set_sk5 入队，
    由 agent 侧的部分合并语义接手（缺字段保留已存值、空密码保留
    已存密码，与本机 P0-4 同款；见 agent action_set_sk5）。开关
    只带本次翻转的键，不带全量 host/port——agent 不需要它们也能
    只改开关。无快照时开关照样入队（agent 自决；面板不知道远程
    存量，不编造 400）。"""
    host = str(data.get("host", "")).strip()
    port = data.get("port")
    toggle_only = (not host and port is None and "password" not in data
                   and "username" not in data)
    if toggle_only:
        if not any(k in data for k in ("enabled", "fail_open",
                                       "udp_over_tcp")):
            return jsonify({"ok": False,
                            "error": "无可更新的字段：请传 enabled / "
                                     "fail_open / udp_over_tcp 之一，"
                                     "或完整 host/port"}), 400
        # 有快照且快照无 host 时与本机同款 400（首次配置须填
        # host/port）；无快照时不拦——agent 自决。
        snap, _last_seen = _node_snapshot(node)
        sk5 = (snap or {}).get("sk5") if isinstance((snap or {}).get("sk5"), dict) else {}
        if sk5 and not sk5.get("host"):
            return jsonify({"ok": False,
                            "error": "host 不能为空（首次配置须填 "
                                     "host/port）"}), 400
        params = {}
        for k in ("enabled", "fail_open", "udp_over_tcp"):
            if k in data:
                # R12-P2-1：开关只接受真布尔或 0/1；"false" 字符串
                # 曾被 bool() 变成 True 而反向执行。
                value, err = _coerce_bool(data[k], k)
                if err:
                    return jsonify({"ok": False, "error": err}), 400
                params[k] = value
        return _enqueue_compat(node["name"], "set_sk5", params, "sk5_save",
                               detail=" toggle-only keys=%s"
                                      % ",".join(sorted(params)))
    if not host:
        return jsonify({"ok": False, "error": "host 不能为空"}), 400
    if not _valid_port(port):
        return jsonify({"ok": False, "error": "port 须为 1-65535 的整数"}), 400
    enabled, err = _strict_bool(data, "enabled", False)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    params = {"host": host, "port": port,
              "username": str(data.get("username", "")),
              "enabled": enabled}
    # P0-4：空密码/缺密码即不传该键——agent 侧保留已存密码；只有
    # 显式非空密码才覆盖；clear_password=true 时照传，由 agent 清掉。
    if data.get("password"):
        params["password"] = str(data["password"])
    if "clear_password" in data:
        # R12-P2-1：只有真 true 才清密码；"false" 字符串是真值，
        # 旧的真值判断曾把它当成清密码。
        clear_pw, err = _coerce_bool(data["clear_password"], "clear_password")
        if err:
            return jsonify({"ok": False, "error": err}), 400
        if clear_pw:
            params["clear_password"] = True
    if "fail_open" in data:
        value, err = _coerce_bool(data["fail_open"], "fail_open")
        if err:
            return jsonify({"ok": False, "error": err}), 400
        params["fail_open"] = value
    if "udp_over_tcp" in data:
        value, err = _coerce_bool(data["udp_over_tcp"], "udp_over_tcp")
        if err:
            return jsonify({"ok": False, "error": err}), 400
        params["udp_over_tcp"] = value
    return _enqueue_compat(node["name"], "set_sk5", params, "sk5_save",
                           detail=" host=%s port=%s enabled=%s"
                                  % (host, port, params["enabled"]))


@app.route("/api/sk5", methods=["POST"])
@login_required
def sk5_save():
    data, err = _json_body()
    if err:
        return jsonify({"ok": False, "error": err}), 400
    # R11-P1-1：先解析节点；远程分支不读本机存量、不写本机配置，
    # 模块检查只在本机分支做。
    node, err = _resolve_compat_node(data)
    if err:
        return err
    if node is not None:
        return _sk5_save_remote(node, data)
    missing = _require_module("sk5_manager")
    if missing:
        return missing
    host = str(data.get("host", "")).strip()
    port = data.get("port")
    username = str(data.get("username", ""))
    # P0-4：面板语义——password 缺失/空串/None = 保留已有密码；只有
    # 显式传非空密码才覆盖；想清掉密码须同时传 clear_password=true。
    # 新版 egress（部分合并）直接按此语义调 set_sk5；旧版全量覆盖
    # set_sk5 则由面板侧解析：空密码用已存密码顶替，清密码传 ""。
    pw = data.get("password")
    # R12-P2-1：clear_password/enabled 只接受真布尔或 0/1；
    # 字符串 "false" 曾被 bool() 变成 True 而反向执行。
    clear_pw, err = _strict_bool(data, "clear_password", False)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    if _SK5_ACCEPTS_CLEAR:
        password = str(pw) if pw is not None and str(pw) != "" else None
    elif pw is None or str(pw) == "":
        password = "" if clear_pw else _stored_sk5_password()
    else:
        password = str(pw)
    enabled, err = _strict_bool(data, "enabled", False)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    # R2-BUG-14 观察：只带 {"enabled": false} 的开关更新。host/port
    # 全缺时不是“缺 host”，而是只改开关——已有配置时直接对存量
    # host/port 做 enable/disable（及 fail_open/udp_over_tcp），
    # 不许 400；无任何存量配置时才报“首次配置须填 host/port”。
    if not host and port is None and "password" not in data \
            and "username" not in data:
        if not any(k in data for k in ("enabled", "fail_open",
                                       "udp_over_tcp")):
            return jsonify({"ok": False,
                            "error": "无可更新的字段：请传 enabled / "
                                     "fail_open / udp_over_tcp 之一，"
                                     "或完整 host/port"}), 400
        # R7-BUG-3: the stored-state read and the mutations below must
        # be one atomic step under _SK5_MUTATE_LOCK. Two concurrent
        # toggle-only saves would otherwise both read the old state
        # and both run the full render + daemon restart.
        with _SK5_MUTATE_LOCK:
            try:
                stored = sk5_get_status()
            except Exception as exc:  # noqa: BLE001
                return jsonify({"ok": False, "error": str(exc)}), 500
            if not stored.get("host"):
                return jsonify({"ok": False,
                                "error": "host 不能为空（首次配置须填 "
                                         "host/port）"}), 400
            # R12-P2-1：开关值已在分支外严格解析（enabled/clear_pw），
            # fail_open/udp_over_tcp 在此解析；非布尔/非 0/1 一律 400，
            # 在触碰存量状态之前拒绝。
            toggle = {}
            for _k in ("fail_open", "udp_over_tcp"):
                if _k in data:
                    _v, _e = _coerce_bool(data[_k], _k)
                    if _e:
                        return jsonify({"ok": False, "error": _e}), 400
                    toggle[_k] = _v
            try:
                if "enabled" in data:
                    # R6-P2-2: toggle-only 开关走 set_sk5 的有效态检查，
                    # 不再直调 enable()/disable()——已启用健康链上的
                    # {"enabled": true} 原来每次都完整重起 sing-box
                    # （在线 VPN 会话断/重建＋耗一次 StartLimitBurst）。
                    # set_sk5 只在模式真翻转时起/停 daemon；已启用且
                    # 有效态健康时纯无操作，已启用但策略缺失/daemon
                    # 死时补修并报 repaired=true。
                    result = sk5_set_sk5(enabled=enabled)
                else:
                    result = stored
                if "fail_open" in toggle:
                    result = sk5_set_fail_open(toggle["fail_open"])
                if "udp_over_tcp" in toggle:
                    result = sk5_set_udp_over_tcp(toggle["udp_over_tcp"])
            except Exception as exc:  # noqa: BLE001
                return jsonify({"ok": False, "error": str(exc)}), 500
        _audit("sk5_save", result="ok",
               detail="toggle-only host=%s port=%s keys=%s"
                      % (stored.get("host"), stored.get("port"),
                         sorted(k for k in ("enabled", "fail_open",
                                            "udp_over_tcp") if k in data)))
        return jsonify({"ok": True, "sk5": result})
    if not host:
        return jsonify({"ok": False, "error": "host 不能为空"}), 400
    if not _valid_port(port):
        return jsonify({"ok": False, "error": "port 须为 1-65535 的整数"}), 400
    # R12-P2-1：fail_open/udp_over_tcp 在触碰状态前严格解析。
    full_toggle = {}
    for _k in ("fail_open", "udp_over_tcp"):
        if _k in data:
            _v, _e = _coerce_bool(data[_k], _k)
            if _e:
                return jsonify({"ok": False, "error": _e}), 400
            full_toggle[_k] = _v
    try:
        # R7-BUG-3: full-form save mutates SK5 state -- serialise it
        # under _SK5_MUTATE_LOCK like the toggle-only branch above.
        with _SK5_MUTATE_LOCK:
            # set_sk5() 在 enabled=True 时立即应用(起 sing-box + 策略路由)
            kwargs = dict(host=host, port=port, username=username,
                          password=password, enabled=enabled)
            if _SK5_ACCEPTS_CLEAR:
                kwargs["clear_password"] = clear_pw
            result = sk5_set_sk5(**kwargs)
            if "fail_open" in full_toggle:
                result = sk5_set_fail_open(full_toggle["fail_open"])
            if "udp_over_tcp" in full_toggle:
                result = sk5_set_udp_over_tcp(full_toggle["udp_over_tcp"])
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500
    # 审计只记 host/port/开关，绝不记 SK5 密码。
    _audit("sk5_save", result="ok",
           detail="host=%s port=%s enabled=%s" % (host, port, enabled))
    return jsonify({"ok": True, "sk5": result})


@app.route("/api/sk5/test", methods=["POST"])
@login_required
def sk5_test():
    # R11-P1-1：指名远程节点时入队测试，不探本机出口。
    node, err = _resolve_compat_node()
    if err:
        return err
    if node is not None:
        return _enqueue_compat(node["name"], "test_sk5", {}, "sk5_test")
    missing = _require_module("sk5_manager")
    if missing:
        return missing
    try:
        raw = sk5_test_proxy()
        # egress 返回扁平字段,面板同时给出嵌套 tcp/udp 视图供前端分开展示
        test = dict(raw)
        test["tcp"] = {"ok": raw.get("tcp_ok"),
                       "latency_ms": raw.get("latency_ms"),
                       "egress_ip": raw.get("egress_ip")}
        test["udp"] = {"ok": raw.get("udp_ok"),
                       "supported": raw.get("udp_ok"),
                       "mode": raw.get("udp_mode"),
                       "note": raw.get("udp_note")}
        _audit("sk5_test", result="ok",
               detail="tcp_ok=%s udp_ok=%s" % (raw.get("tcp_ok"),
                                               raw.get("udp_ok")))
        return jsonify({"ok": True, "test": test})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/sk5/enable", methods=["POST"])
@login_required
def sk5_enable():
    # R11-P1-1：指名远程节点时入队 enable_sk5（Worker 同款动作），
    # 不碰本机 sing-box。
    node, err = _resolve_compat_node()
    if err:
        return err
    if node is not None:
        return _enqueue_compat(node["name"], "enable_sk5", {}, "sk5_enable")
    missing = _require_module("sk5_manager")
    if missing:
        return missing
    try:
        # R6-P2-2: 不再直调 enable()——已启用健康链上每点一次
        # 即一次完整重起。走 set_sk5(enabled=True) 的有效态检查：
        # 健康即纯无操作 200，缺策略只补策略，daemon 死才完整
        # enable；未配置过 SK5 时仍 500（与旧 enable() 同口径）。
        # R7-BUG-3: serialise under _SK5_MUTATE_LOCK -- two concurrent
        # enables must not both run the full render + daemon restart.
        with _SK5_MUTATE_LOCK:
            result = sk5_set_sk5(enabled=True)
        _audit("sk5_enable", result="ok")
        return jsonify({"ok": True, "result": result})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/sk5/disable", methods=["POST"])
@login_required
def sk5_disable():
    # R11-P1-1：指名远程节点时入队 disable_sk5（Worker 同款动作），
    # 不碰本机 sing-box。
    node, err = _resolve_compat_node()
    if err:
        return err
    if node is not None:
        return _enqueue_compat(node["name"], "disable_sk5", {}, "sk5_disable")
    missing = _require_module("sk5_manager")
    if missing:
        return missing
    try:
        # 与 enable 路对称的同族收敛（R6-P2-2 未点名、同一机制）：
        # 已禁用链上直调 disable() 同样每次完整重起。走
        # set_sk5(enabled=False)：真翻转时调 disable()，已禁用
        # 时纯写盘不动 daemon。从未配置过 SK5 时沿用旧行为返回
        # 当前状态 200（set_sk5 会因无 host 而 500，不合旧口径）。
        # R7-BUG-3: the stored-state read and the disable must be one
        # atomic step under _SK5_MUTATE_LOCK (see _SK5_MUTATE_LOCK):
        # two concurrent disables would otherwise both read
        # enabled=true and both restart the daemon.
        with _SK5_MUTATE_LOCK:
            stored = sk5_get_status()
            if not stored.get("host"):
                return jsonify({"ok": True, "result": stored})
            result = sk5_set_sk5(enabled=False)
        _audit("sk5_disable", result="ok")
        return jsonify({"ok": True, "result": result})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/sk5/fail-open", methods=["POST"])
@login_required
def sk5_fail_open():
    """切换断链策略: True=故障回直连, False=默认断网保护(黑洞)."""
    data, err = _json_body()
    if err:
        return jsonify({"ok": False, "error": err}), 400
    # R11-P1-1：指名远程节点时只入队本次翻转的键（agent set_sk5
    # 部分合并，不需要全量 host/port）。
    node, err = _resolve_compat_node(data)
    if err:
        return err
    # R12-P2-1：fail_open 只接受真布尔或 0/1；"false" 字符串
    # 曾被 bool() 变成 True 而反向执行。
    fail_open, err = _strict_bool(data, "fail_open", False)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    if node is not None:
        return _enqueue_compat(node["name"], "set_sk5",
                               {"fail_open": fail_open},
                               "sk5_fail_open")
    missing = _require_module("sk5_manager")
    if missing:
        return missing
    try:
        # R7-BUG-3 同族：fail_open 与 udp_over_tcp 的翻转同样是
        # read-check-apply，须与 enable/disable/save 用同一把锁串行化，
        # 否则并发翻转会双双重起 daemon。
        with _SK5_MUTATE_LOCK:
            result = sk5_set_fail_open(fail_open)
        _audit("sk5_fail_open", result="ok",
               detail="fail_open=%s" % fail_open)
        return jsonify({"ok": True, "result": result})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/sk5/udp-over-tcp", methods=["POST"])
@login_required
def sk5_udp_over_tcp():
    """切换 UDP 模式: True=UoT 封装走 TCP, False=原生 UDP ASSOCIATE."""
    data, err = _json_body()
    if err:
        return jsonify({"ok": False, "error": err}), 400
    # R11-P1-1：指名远程节点时只入队本次翻转的键（agent set_sk5
    # 部分合并，不需要全量 host/port）。
    node, err = _resolve_compat_node(data)
    if err:
        return err
    # R12-P2-2：读 udp_over_tcp 优先、回落 enabled（与 Worker 的
    # handleCompatSk5Toggle 同款）；旧代码两分支都读 enabled，
    # {"udp_over_tcp": true} 回 200 但结果 false。
    # R12-P2-1：值只接受真布尔或 0/1。
    uot, err = _toggle_value(data, "udp_over_tcp", fallback="enabled",
                             default=False)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    if node is not None:
        return _enqueue_compat(node["name"], "set_sk5",
                               {"udp_over_tcp": uot},
                               "sk5_udp_over_tcp")
    missing = _require_module("sk5_manager")
    if missing:
        return missing
    try:
        # R7-BUG-3 同族：见 sk5_fail_open。
        with _SK5_MUTATE_LOCK:
            result = sk5_set_udp_over_tcp(uot)
        _audit("sk5_udp_over_tcp", result="ok",
               detail="udp_over_tcp=%s" % uot)
        return jsonify({"ok": True, "result": result})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500


# ---------------- 节点注册（管理员） ----------------
# token 明文只在注册/轮换时返回一次，库里只存 SHA-256 哈希。
# 注册时绑定的 panel_url 必须与给 agent 的 --panel-url 逐字一致，
# 否则 agent poll 时认领守卫会 403（见 _check_panel_claim）。

@app.route("/api/nodes", methods=["GET"])
@login_required
def nodes_list():
    conn = _db()
    rows = conn.execute(
        "SELECT name, panel_url, created_at, last_seen, last_status"
        " FROM nodes ORDER BY name").fetchall()
    conn.close()
    nodes = []
    for r in rows:
        try:
            last_status = json.loads(r["last_status"]) if r["last_status"] else None
        except ValueError:
            last_status = None
        nodes.append({"name": r["name"], "panel_url": r["panel_url"],
                      "created_at": r["created_at"],
                      "last_seen": r["last_seen"],
                      "last_status": last_status})
    return jsonify({"ok": True, "nodes": nodes})


@app.route("/api/nodes", methods=["POST"])
@login_required
def nodes_register():
    data, err = _json_body()
    if err:
        return jsonify({"ok": False, "error": err}), 400
    name = str(data.get("name", "")).strip()
    if not _NODE_NAME_RE.match(name):
        return jsonify({"ok": False, "error": "节点名非法：只允许字母/数字/_/-，1–32 字符"}), 400
    panel_url = str(data.get("panel_url", "") or "").strip().rstrip("/")
    if panel_url and not panel_url.startswith(("http://", "https://")):
        return jsonify({"ok": False, "error": "panel_url 须以 http:// 或 https:// 开头"}), 400
    if not panel_url:
        panel_url = request.host_url.rstrip("/")
    if _get_node(name):
        return jsonify({"ok": False, "error": "节点已存在：%s" % name}), 409
    token = secrets.token_urlsafe(32)
    conn = _db()
    conn.execute(
        "INSERT INTO nodes (name, token_hash, panel_url, created_at)"
        " VALUES (?,?,?,?)",
        (name, _hash_token(token), panel_url, _utcnow_iso()))
    conn.commit()
    conn.close()
    with _QUEUE_LOCK:
        state = _load_queue()
        state["queue"].setdefault(name, [])
        _save_queue(state)
    _audit("node_register", result="ok",
           detail="name=%s panel_url=%s" % (name, panel_url))
    return jsonify({"ok": True,
                    "node": {"name": name, "panel_url": panel_url},
                    "token": token,
                    "note": "token 只返回这一次，请当场记下并传给装机命令；"
                            "丢失只能轮换，不可找回"}), 201


@app.route("/api/nodes/<name>", methods=["DELETE"])
@login_required
def nodes_revoke(name):
    if not _NODE_NAME_RE.match(name):
        return jsonify({"ok": False, "error": "节点名非法"}), 400
    if not _get_node(name):
        return jsonify({"ok": False, "error": "节点不存在：%s" % name}), 404
    # R14-P2-1：先隔离坏条目再删库行——扫队列必须发生在 DELETE 之前：
    # 若队列含非对象条目，下面的 cmds 迭代会 500；而 500 若发生在删库
    # 之后，节点已消失、其 queued 命令却无人标 failed，重试 DELETE 只会
    # 404，命令永久滞留。先扫后删，隔离失败时节点仍在、可重试。
    with _QUEUE_LOCK:
        state = _load_queue()
        _fail_malformed_cmds(state)
        _save_queue(state)
    conn = _db()
    conn.execute("DELETE FROM nodes WHERE name = ?", (name,))
    conn.commit()
    conn.close()
    with _QUEUE_LOCK:
        state = _load_queue()
        state["queue"].pop(name, None)
        # P1-6：吊销时 queued 与 sent 态命令一并标失败（旧代码只处理
        # queued，sent 的命令会永久卡住）。isinstance 是纵深兜底——
        # 上面已扫过队列，此处只防两次读盘之间手改文件又塞进坏条目。
        for cmd_id in [cid for cid, c in state["cmds"].items()
                       if isinstance(c, dict)
                       and c.get("node") == name
                       and c.get("status") in ("queued", "sent")]:
            state["cmds"][cmd_id]["status"] = "failed"
            state["cmds"][cmd_id]["error"] = "节点已吊销"
            state["cmds"][cmd_id]["finished_at"] = _utcnow_iso()
        _save_queue(state)
    _audit("node_revoke", node=name, result="ok",
           detail="token 已作废，该节点后续 poll 一律 401")
    return jsonify({"ok": True, "node": name})


@app.route("/api/nodes/<name>/rotate", methods=["POST"])
@login_required
def nodes_rotate(name):
    if not _NODE_NAME_RE.match(name):
        return jsonify({"ok": False, "error": "节点名非法"}), 400
    if not _get_node(name):
        return jsonify({"ok": False, "error": "节点不存在：%s" % name}), 404
    token = secrets.token_urlsafe(32)
    conn = _db()
    conn.execute("UPDATE nodes SET token_hash = ? WHERE name = ?",
                 (_hash_token(token), name))
    conn.commit()
    conn.close()
    _audit("node_rotate", node=name, result="ok",
           detail="旧 token 立即作废，须重跑 install-agent.sh 带新 token")
    return jsonify({"ok": True, "node": {"name": name}, "token": token,
                    "note": "新 token 只返回这一次；旧 token 立即失效"})


# ---------------- 管理员下发命令 / 查结果 ----------------

@app.route("/api/cmd", methods=["POST"])
@login_required
def cmd_create():
    data, err = _json_body()
    if err:
        return jsonify({"ok": False, "error": err}), 400
    node_name = str(data.get("node", "")).strip()
    action = str(data.get("action", "")).strip()
    if not node_name:
        return jsonify({"ok": False, "error": "须指定 node"}), 400
    if action not in AGENT_ACTIONS:
        return jsonify({"ok": False, "error": "非法 action：%s" % action,
                        "allowed": sorted(AGENT_ACTIONS)}), 400
    if not _get_node(node_name):
        return jsonify({"ok": False, "error": "节点不存在：%s" % node_name}), 404
    params = data.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return jsonify({"ok": False, "error": "params 须为 JSON 对象"}), 400
    cmd = _enqueue_command(node_name, action, params)
    _audit("cmd_enqueue", node=node_name, result="ok",
           detail="action=%s id=%s" % (action, cmd["id"]))
    return jsonify({"ok": True, "cmd_id": cmd["id"], "node": node_name,
                    "action": action, "status": "queued"}), 202


@app.route("/api/cmd/<cmd_id>", methods=["GET"])
@login_required
def cmd_get(cmd_id):
    with _QUEUE_LOCK:
        state = _load_queue()
        # R12-P1-1/P2-7：先隔离坏条目（标 failed＋审计），再重投超时命令。
        _fail_malformed_cmds(state)
        _requeue_stale_sent(state)
        _save_queue(state)
        cmd = state["cmds"].get(cmd_id)
    if not cmd:
        return jsonify({"ok": False, "error": "命令不存在：%s" % cmd_id}), 404
    if not isinstance(cmd, dict):
        # _fail_malformed_cmds 已删非对象条目；此处仅作兜底。
        return jsonify({"ok": False, "error": "命令不存在：%s" % cmd_id}), 404
    # R12-P2-7：输出一律 .get()＋规整读——手改条目缺键／错型时
    # 仍回 200 展示残值，绝不 500。
    retries = _safe_int(cmd.get("retries"))
    params = cmd.get("params")
    out = {"ok": True, "id": cmd.get("id", cmd_id), "node": cmd.get("node"),
           "action": cmd.get("action"),
           "params": _redact_dict(params) if isinstance(params, dict) else {},
           "status": cmd.get("status"), "result": cmd.get("result"),
           "error": cmd.get("error"), "created_at": cmd.get("created_at"),
           "sent_at": cmd.get("sent_at"), "finished_at": cmd.get("finished_at"),
           "retries": retries if retries is not None else 0}
    if cmd.get("status") == "sent" and cmd.get("sent_at"):
        try:
            sent = datetime.fromisoformat(cmd.get("sent_at"))
            if sent.tzinfo is None:
                # naive 按 UTC 解读（与 _requeue_stale_sent 同款）；
                # 否则与 aware 的 now 相减抛 TypeError。
                sent = sent.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - sent).total_seconds()
            if age > SENT_TIMEOUT_SECONDS:
                out["timeout_hint"] = ("已下发超过 %d 秒未回执：agent 可能已死"
                                       "或离线，系统将自动重新下发"
                                       % SENT_TIMEOUT_SECONDS)
        except (ValueError, TypeError):
            # R12-P2-7：sent_at 数字等错型值只跳过提示，不 500。
            pass
    if cmd.get("status") == "queued" and (retries or 0) > 0:
        out["timeout_hint"] = ("曾超时未回执，已自动重新下发 %d 次"
                               "（上限 %d 次）"
                               % (retries, SENT_MAX_RETRIES))
    return jsonify(out)


@app.route("/api/nodes/<node>/users/<user>/ovpn", methods=["GET"])
@login_required
def node_user_ovpn(node, user):
    """agent 模式下 create_user 回执的 .ovpn（管理员下载用）。"""
    # R13-P2-3：与 ?node= 分支同款——先查节点快照的 users 状态，
    # 吊销／过期一律 403，绝不下发已作废凭证；无快照／用户不在快照
    # 里时按旧行为下发回执（快照只是 agent 上报的状态，无快照≠已吊销）。
    node_rec, err = _lookup_node(node)
    if err:
        return err
    snap_user = _snapshot_users(node_rec).get(user)
    reason = _download_block_reason(
        snap_user.get("status") if isinstance(snap_user, dict) else None)
    if reason:
        return jsonify({"ok": False,
                        "error": "用户 %s %s" % (user, reason)}), 403
    with _QUEUE_LOCK:
        state = _load_queue()
        # R14-P2-1：先隔离坏条目再读回执——ovpn 段的非对象回执不扫
        # 掉，下面的 rec.get("ovpn") 即 500（与 ?node= 分支的
        # isinstance 守卫同款形状，扫＋守卫双层）。
        _fail_malformed_cmds(state)
        _save_queue(state)
        rec = state["ovpn"].get("%s:%s" % (node, user))
    if not isinstance(rec, dict) or not rec.get("ovpn"):
        return jsonify({"ok": False,
                        "error": "该用户 .ovpn 尚未生成/上报：先建用户，"
                                 "等 agent 回执后再下载"}), 404
    return app.response_class(
        rec["ovpn"], mimetype="application/x-openvpn-profile",
        headers={"Content-Disposition":
                 'attachment; filename="%s.ovpn"' % user})


# ---------------- 审计日志查询（管理员） ----------------

@app.route("/api/audit", methods=["GET"])
@login_required
def audit_list():
    try:
        limit = int(request.args.get("limit", "100"))
    except ValueError:
        limit = 100
    limit = max(1, min(limit, 500))
    conn = _db()
    rows = conn.execute(
        "SELECT id, ts, actor, action, node, result, detail FROM audit_log"
        " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return jsonify({"ok": True, "audit": [dict(r) for r in rows]})


# ---------------- agent 接口（节点 token 鉴权，不走管理员会话） ----------------

@app.route("/api/agent/poll", methods=["POST"])
def agent_poll():
    node, err = _agent_auth()
    if err:
        _audit("agent_poll_auth_fail", actor="agent:unknown",
               result="denied", detail="token 无效或缺失")
        return err
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}
    ok, claim = _check_panel_claim(node, data)
    if not ok:
        _audit("agent_poll_panel_mismatch", actor="agent:" + node["name"],
               node=node["name"], result="denied", detail=claim)
        return jsonify({"ok": False, "error": claim}), 403
    status = data.get("status")
    if isinstance(status, dict):
        _touch_node(node["name"], status)
    else:
        _touch_node(node["name"], {})
    with _QUEUE_LOCK:
        state = _load_queue()
        # R12-P1-1：先隔离坏条目（标 failed＋审计），再重投超时命令；
        # 一条手改坏记录绝不能让本轮 poll 500。
        _fail_malformed_cmds(state)
        # P1-6：先把超时的 sent 命令打回 queued，本轮 poll 即可重新下发。
        _requeue_stale_sent(state)
        ids = state["queue"].get(node["name"], [])
        if not isinstance(ids, list):
            # 手改队列把某节点队列写成非列表时，按空队列处理。
            ids = []
        commands = []
        for cmd_id in ids:
            cmd = state["cmds"].get(cmd_id)
            if not isinstance(cmd, dict):
                continue
            if cmd.get("status") != "queued":
                # R17-P1-1：下发列表只收 queued 命令——队列数组里的 id
                # 只是“候选”，sweep 标 failed、超时标失败、已 sent 的
                # 命令一律不下发（旧代码 append 在守卫块外，failed 的
                # init_pki 同轮 poll 照常下发，agent 会重建 CA）。
                continue
            cmd["status"] = "sent"
            cmd["sent_at"] = _utcnow_iso()
            params = cmd.get("params")
            commands.append({"id": cmd_id, "action": cmd.get("action"),
                             "params": params
                             if isinstance(params, dict) else {}})
        state["queue"][node["name"]] = []
        _save_queue(state)
    out = {"ok": True, "node": node["name"], "commands": commands,
           "poll_interval_s": 5}
    if claim == "unverified":
        out["panel_url_unverified"] = True
    return jsonify(out)


@app.route("/api/agent/report", methods=["POST"])
def agent_report():
    node, err = _agent_auth()
    if err:
        _audit("agent_report_auth_fail", actor="agent:unknown",
               result="denied", detail="token 无效或缺失")
        return err
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "请求体须为 JSON 对象"}), 400
    ok, claim = _check_panel_claim(node, data)
    if not ok:
        _audit("agent_report_panel_mismatch", actor="agent:" + node["name"],
               node=node["name"], result="denied", detail=claim)
        return jsonify({"ok": False, "error": claim}), 403
    # agent 发 id，Cloudflare Worker 侧用 cmd_id：两个都接受。
    cmd_id = data.get("cmd_id") or data.get("id")
    if not cmd_id:
        # 纯心跳：无命令 id，只有状态快照时只更新快照与 last_seen。
        snap = data.get("status")
        if isinstance(snap, dict):
            _touch_node(node["name"], snap)
        return jsonify({"ok": True, "heartbeat": True})
    with _QUEUE_LOCK:
        state = _load_queue()
        # R12-P1-1：先隔离坏条目（标 failed＋审计）并落盘，再处理回执。
        _fail_malformed_cmds(state)
        _save_queue(state)
        cmd = state["cmds"].get(str(cmd_id))
        if not cmd:
            return jsonify({"ok": False,
                            "error": "命令不存在：%s" % cmd_id}), 404
        if not isinstance(cmd, dict):
            # _fail_malformed_cmds 已删非对象条目；此处仅作兜底。
            return jsonify({"ok": False,
                            "error": "命令不存在：%s" % cmd_id}), 404
        if cmd.get("node") != node["name"]:
            return jsonify({"ok": False, "error": "该命令不属于本节点"}), 403
        action = cmd.get("action")
        if (not isinstance(action, str) or action not in AGENT_ACTIONS
                or (isinstance(cmd.get("error"), str)
                    and cmd["error"].startswith("队列条目损坏"))):
            # R12-P1-1：坏条目已被标 failed；agent 的回执无有效动作可落，
            # 不复活该条目，200 回 failed 让 agent 继续下一条。
            return jsonify({"ok": True, "cmd_id": cmd.get("id", str(cmd_id)),
                            "status": "failed",
                            "error": "队列条目损坏，未应用回执"}), 200
        if cmd.get("status") != "sent":
            # R17-P1-1：回执只接受 sent 态命令的；queued/done/failed 的
            # 回执是陈旧或越权 agent 行为（agent 没收到过该命令就无权
            # 翻它），不翻状态，409 诚实拒绝并审计。坏条目分支在前，
            # “队列条目损坏”条目仍走既有的 200 回 failed，不受影响。
            _audit("agent_report_not_sent", actor="agent:" + node["name"],
                   node=node["name"], result="denied",
                   detail="action=%s id=%s status=%s"
                          % (action, cmd.get("id"), cmd.get("status")))
            return jsonify({"ok": False,
                            "error": "命令未下发（status=%s），回执不予接受"
                                     % cmd.get("status")}), 409
        succeeded = data.get("ok") is True
        cmd["status"] = "done" if succeeded else "failed"
        cmd["result"] = data.get("result")
        cmd["error"] = (None if succeeded else
                        (str(data.get("error")) if data.get("error")
                         else "agent 执行失败"))
        cmd["finished_at"] = _utcnow_iso()
        if (action == "create_user" and succeeded
                and isinstance(cmd["result"], dict)):
            params = cmd.get("params")
            user = params.get("name") if isinstance(params, dict) else None
            ovpn = cmd["result"].get("ovpn")
            if user and isinstance(ovpn, str):
                state["ovpn"]["%s:%s" % (node["name"], user)] = {
                    "ovpn": ovpn, "at": _utcnow_iso()}
        if action == "get_status" and succeeded:
            # R11-P1-1：给快照打 at=回执时刻，远程读据此算 stale/age_s
            # （与 Worker 的 status:<node> at 同款）；心跳不打 at。
            snap = dict(cmd["result"]) if isinstance(cmd["result"], dict) else {}
            snap["at"] = _utcnow_iso()
            _touch_node(node["name"], snap)
        _save_queue(state)
    # 审计只记动作与成败，绝不记 result（里面可能有 .ovpn 私钥）。
    _audit("agent_report", actor="agent:" + node["name"],
           node=node["name"], result="done" if succeeded else "failed",
           detail="action=%s id=%s" % (action, cmd.get("id")))
    return jsonify({"ok": True, "cmd_id": cmd.get("id"),
                    "status": cmd.get("status")})


@app.route("/api/agent/bundle", methods=["GET"])
def agent_bundle():
    """下发 agent 安装包（agent/ + core/ + egress/ 打成的 tar.gz）。

    注意：本接口不设鉴权——install-agent.sh 在装机时就是无鉴权
    curl 下来的。包里只有代码，没有任何凭据（节点 token 是装机时
    --token 参数单独传的，不在包里），公开下发与代码公开等价。
    凭据的唯一关口是节点 token + panel_url 认领守卫。"""
    buf = _build_agent_bundle()
    return send_file(buf, mimetype="application/gzip", as_attachment=True,
                     download_name="ovpn-agent-bundle.tar.gz")


def _build_agent_bundle():
    """确定性打包：gzip mtime=0 且 tar 条目 mtime/uid/gid 归零。

    否则两次打包的字节不同，/api/agent/bundle.sha256 的哈希就对不上
    另一次下载的包，fail-closed 会误杀正常安装。"""
    buf = io.BytesIO()
    gz = gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0)
    with tarfile.open(fileobj=gz, mode="w") as tf:
        for sub in ("agent", "core", "egress"):
            root = os.path.join(PROJECT_DIR, sub)
            for dirpath, dirnames, filenames in os.walk(root):
                # P2-4：目录序也要排定——只排文件名时 tar 条目顺序仍
                # 依赖文件系统 readdir 顺序，换机器可能让 bundle 与
                # bundle.sha256 对不上，fail-closed 误杀正常安装。
                dirnames[:] = sorted(
                    d for d in dirnames if d != "__pycache__")
                for fn in sorted(filenames):
                    if fn.endswith((".pyc", ".pyo")):
                        continue
                    full = os.path.join(dirpath, fn)
                    arc = os.path.relpath(full, PROJECT_DIR)
                    info = tf.gettarinfo(full, arc)
                    info.mtime = 0
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    with open(full, "rb") as f:
                        tf.addfile(info, f)
    gz.close()
    buf.seek(0)
    return buf


@app.route("/api/agent/bundle.sha256", methods=["GET"])
def agent_bundle_sha256():
    """与 /api/agent/bundle 同一份确定性包的 SHA-256。

    install-agent.sh 装机时先取本端点再取包，哈希对不上即拒绝安装
    （fail-closed）。无鉴权公开下发，与 bundle 本身同理：包里只有代码。"""
    buf = _build_agent_bundle()
    digest = hashlib.sha256(buf.read()).hexdigest()
    return "%s  ovpn-agent-bundle.tar.gz\n" % digest, 200, {
        "Content-Type": "text/plain; charset=utf-8"}


@app.route("/install-agent.sh", methods=["GET"])
def install_agent_script():
    """装机引导脚本：无鉴权公开下发（脚本本身不含任何凭据，
    token 由装机命令 --token 参数传入）。"""
    return send_from_directory(os.path.join(PROJECT_DIR, "agent"),
                               "install-agent.sh",
                               mimetype="text/x-shellscript")


@app.route("/install-agent.sh.sha256", methods=["GET"])
def install_agent_script_sha256():
    """install-agent.sh 的 SHA-256（`sha256sum -c` 可读格式）。

    Cloudflare Worker 的安装命令先取本端点验脚本再执行；无鉴权
    公开下发，与脚本本身同理：脚本里只有代码，没有任何凭据。"""
    path = os.path.join(PROJECT_DIR, "agent", "install-agent.sh")
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    return "%s  install-agent.sh\n" % digest, 200, {
        "Content-Type": "text/plain; charset=utf-8"}


if __name__ == "__main__":
    _ensure_admin_password()
    app.run(host="0.0.0.0", port=8443)
