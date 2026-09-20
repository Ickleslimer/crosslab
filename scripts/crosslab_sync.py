"""crosslab_sync.py — test-gated propagation of the local crosslab MCP.

Same model as desktop-control-mcp's desktop_sync.py (codetalker's pipeline,
minus PyPI — nothing is published anywhere): the launch form is a
**receipted editable tool install**,

    uv tool install --editable --force --from <repo> crosslab

so the shim at ~/.local/bin/crosslab.exe always runs THIS checkout — source
edits are live at the next server start with zero publish step, and the uv
receipt prevents the orphaned-env resolution rot codetalker's first live run
diagnosed. What still needs automation, this script does:

  1. tests   — run tests/ in a clean ephemeral env built from
               pyproject.toml (the global python is known-polluted);
               a failure aborts everything, fail-closed.
  2. env     — `uv tool install --force` re-resolves dependencies so
               dependency/entry-point changes propagate too (code changes
               need nothing: the shim is already live). Skipped when
               pyproject.toml is unchanged since the last install — a live
               harness server holds the env on Windows and blocks --force.
  3. registry— point every harness entry at the shim (create when missing),
               preserving other servers, BOM, and CRLF style; one-shot .bak
               on modification.
  4. probe   — spawn the entry AS WRITTEN in the live registry file and
               run a real MCP handshake (initialize + tools/list). The
               check whose absence shipped a bare `crosslab`: the shim
               answered --help, so shim_alive() passed, while every harness
               spawn printed usage and exited ("Connection closed").
  5. hooks   — self-heal core.hooksPath=hooks so a fresh clone keeps
               auto-sync (git never clones config; the hook itself IS
               tracked in hooks/post-commit).

crosslab-specific deltas from desktop_sync.py:

  * NO env block in the registry entries (desktop-control carried gates in
    env). CrossLab agent identity self-manages: node startup probes local
    harness configs (Codex / OpenCode / Cursor CLI) and agents can set the
    profile via MCP (`crosslab_set_agent_profile`) — a hardcoded
    CROSSLAB_HARNESS would lie on a multi-harness machine like this one.
  * Codex IS a target here (it was excluded for desktop-control because of
    its built-in computer use — that reason does not apply to crosslab).
    Codex config is TOML, so the merge is targeted line surgery inside
    ~/.codex/config.toml: only the [mcp_servers.crosslab] block is touched
    and the user's per-tool approval subtables (the pattern Codex uses for
    codetalker, e.g. [mcp_servers.codetalker.tools.*]) survive untouched.
  * Antigravity has TWO config candidates on this machine:
    ~/.gemini/antigravity/mcp_config.json (carries desktop-control — proven
    live by that server actually running) and ~/.gemini/config/mcp_config.json
    (the path crosslab's own `mcp install` targets). Both are synced to keep
    the pair consistent — other servers preserved in each.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DIST = "crosslab"
SHIM = Path.home() / ".local" / "bin" / ("crosslab.exe" if os.name == "nt" else "crosslab")
# Launch contract, mirroring crosslab's own installer templates
# (crosslab/mcp/install.py): the shim MUST be given the `mcp` subcommand —
# bare `crosslab` prints usage and exits, which harnesses surface as
# "Connection closed. Failed to start MCP server". The node URL is explicit
# so the entry is self-describing (same default as the installer).
SHIM_ARGS = ["mcp", "--node-url", "http://127.0.0.1:8765"]

# Harnesses to keep on the shim launch form. `create`: write the file when
# missing (fresh-machine case); otherwise skip with a note.
SERVERS: dict[str, dict] = {
    "freebuff": {"path": Path.home() / ".agents" / "mcp.json", "create": True},
    "cursor": {"path": Path.home() / ".cursor" / "mcp.json", "create": True},
    "antigravity": {
        "path": Path.home() / ".gemini" / "antigravity" / "mcp_config.json",
        "create": True,
    },
    "antigravity-config": {
        "path": Path.home() / ".gemini" / "config" / "mcp_config.json",
        "create": True,
    },
}
# TOML targets (Codex): merged by targeted line surgery, not JSON.
TOML_SERVERS: dict[str, dict] = {
    "codex": {"path": Path.home() / ".codex" / "config.toml", "create": False},
}
# Not a config target: no Claude Desktop config exists on this machine.
SKIP = {"claude-desktop": "no config present on this machine"}

ENTRY_NAME = "crosslab"


def die(msg: str) -> None:
    print(f"[crosslab-sync] FATAL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def step(msg: str) -> None:
    print(f"[sync] {msg}")


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print("  $ " + " ".join(cmd))
    r = subprocess.run(cmd, **kw)
    if r.returncode != 0:
        die(f"command failed ({r.returncode}): {' '.join(cmd)}")
    return r


# ─── 1. tests (ephemeral, clean) ─────────────────────────────────────────────


def run_tests() -> None:
    step("running tests in a clean ephemeral env (pyproject deps + pytest)")
    run(
        [
            "uv", "run", "--isolated",
            "--with-editable", str(REPO),
            "--with", "pytest",
            "--with", "pytest-asyncio",
            "--", "python", "-m", "pytest", "tests/", "-q",
        ],
        cwd=str(REPO),
    )


# ─── 2. shim env (receipted editable tool install) ──────────────────────────


def shim_alive() -> bool:
    if not SHIM.is_file():
        return False
    try:
        r = subprocess.run([str(SHIM), "--help"], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


# Remembers the pyproject.toml state the tool env was last built from, so
# unchanged commits skip the reinstall: a live harness server (launched from
# this env) makes `--force` impossible on Windows — it cannot delete files a
# running process holds. Reinstalls therefore happen only when deps or entry
# points actually change, which in practice means the server is not running.
STAMP = Path.home() / ".crosslab.env-stamp"


def _pyproject_stamp() -> str:
    return hashlib.sha256((REPO / "pyproject.toml").read_bytes()).hexdigest()


def refresh_env(dry: bool) -> None:
    want = _pyproject_stamp()
    have = STAMP.read_text(encoding="utf-8").strip() if STAMP.is_file() else ""
    if have == want and shim_alive():
        print("  env current (pyproject unchanged since last install) — reinstall skipped")
        return
    if dry:
        print("  [dry] would run: uv tool install --editable --force --from "
              f"{REPO} {DIST}")
        return
    if have == want:
        step("shim not answering — repairing tool env")
    else:
        step("refreshing receipted editable tool env (deps or entry points changed)")
    run(
        [
            "uv", "tool", "install", "--editable", "--force",
            "--from", str(REPO), DIST,
        ]
    )
    if not shim_alive():
        die(f"shim at {SHIM} does not answer --help after reinstall")
    # Written only after a proven-good install, so a crash anywhere above
    # leaves the old stamp in place and the next run retries the install.
    STAMP.write_text(want + "\n", encoding="utf-8")


# ─── 3a. JSON harness registries ─────────────────────────────────────────────


def _desired_entry() -> dict:
    # Deliberately env-free: agent identity self-manages (see module docstring).
    return {"command": str(SHIM), "args": list(SHIM_ARGS)}


def _read_json(path: Path) -> tuple[dict, bool, bool]:
    """Return (data, had_bom, crlf). Corrupt files raise."""
    raw = path.read_bytes()
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    if had_bom:
        raw = raw[3:]
    crlf = b"\r\n" in raw
    return json.loads(raw.decode("utf-8")), had_bom, crlf


def _write_json(path: Path, data: dict, had_bom: bool, crlf: bool) -> None:
    text = json.dumps(data, indent=2)
    if crlf:
        text = text.replace("\n", "\r\n") + "\r\n"
    else:
        text += "\n"
    path.write_bytes(text.encode("utf-8-sig" if had_bom else "utf-8"))


def sync_registry(name: str, spec: dict, dry: bool) -> None:
    path: Path = spec["path"]
    step(f"{name} tier: {path}")
    if not path.exists():
        if not spec["create"]:
            print("  no config present — skipped (create=false)")
            return
        if dry:
            print("  [dry] would create file with the shim entry")
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(path, {"mcpServers": {ENTRY_NAME: _desired_entry()}}, False, False)
        print("  [ok] created with the shim entry")
        return

    data, had_bom, crlf = _read_json(path)
    servers = data.setdefault("mcpServers", {})
    current = servers.get(ENTRY_NAME)
    if current == _desired_entry():
        print("  [ok] current")
        return
    if dry:
        print(f"  [dry] would {'add' if current is None else 'replace'} entry -> {SHIM}")
        return
    if current is not None:
        bak = path.with_suffix(path.suffix + ".bak")
        if not bak.exists():  # one-shot backup per file
            bak.write_bytes(path.read_bytes())
            print(f"  backup -> {bak.name}")
    servers[ENTRY_NAME] = _desired_entry()
    _write_json(path, data, had_bom, crlf)
    print(f"  [ok] {'added' if current is None else 'updated'} "
          f"(other servers preserved: {len(servers) - 1})")


# ─── 3b. Codex TOML registry ─────────────────────────────────────────────────


def _toml_str(s: str) -> str:
    """TOML basic string literal (backslashes escaped) — valid for paths."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def sync_codex_toml(name: str, spec: dict, dry: bool) -> None:
    path: Path = spec["path"]
    step(f"{name} tier: {path}")
    if not path.exists():
        if not spec["create"]:
            print("  no config present — skipped (create=false)")
            return
        die(f"{path} not found and create=false — cannot wire {name}")

    raw = path.read_bytes()
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")  # newline translation off via bytes path
    crlf = "\r\n" in text
    nl = "\r\n" if crlf else "\n"

    header = f"[mcp_servers.{ENTRY_NAME}]"
    cmd_line = f"command = {_toml_str(str(SHIM))}"
    args_line = f"args = {json.dumps(SHIM_ARGS)}"  # TOML inline array
    desired_block = header + nl + cmd_line + nl + args_line + nl

    if header in text:
        # Block exists: rewrite ONLY the command/args lines inside it, so
        # per-tool approval subtables ([mcp_servers.crosslab.tools.*]) and
        # env subtables survive untouched.
        lines = text.split(nl)
        start = next(i for i, ln in enumerate(lines) if ln.strip() == header)
        end = next((i for i in range(start + 1, len(lines))
                    if lines[i].startswith("[")), len(lines))
        orig_body = lines[start + 1:end]
        body: list[str] = []
        for ln in orig_body:
            if (ln.startswith("command ") or ln.startswith("command=")
                    or ln.startswith("args ") or ln.startswith("args=")):
                continue  # regenerated below from the desired form
            body.append(ln)
        body = [cmd_line, args_line] + body
        # No-op detection is a plain list comparison, so an already-current
        # block is recognized and NEVER rewritten (subtables included).
        if body == orig_body:
            print("  [ok] current")
            return
        new_text = nl.join(lines[:start] + [header] + body + lines[end:])
    else:
        if dry:
            print(f"  [dry] would append {header} block -> {SHIM}")
            return
        new_text = text
        if new_text and not new_text.endswith(nl):
            new_text += nl
        new_text += nl + desired_block

    if dry:
        print(f"  [dry] would rewrite {header} block inside {path} "
              "(only command/args lines; subtables preserved)")
        return
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():  # one-shot backup per file
        bak.write_bytes(raw)
        print(f"  backup -> {bak.name}")
    path.write_bytes(new_text.encode("utf-8-sig" if had_bom else "utf-8"))
    print(f"  [ok] {'appended' if header not in text else 'updated'} "
          f"{header} (everything else byte-identical)")


# ─── 4. launch probe ─────────────────────────────────────────────────────────


def _probe_fail(proc: subprocess.Popen, msg: str) -> None:
    """Kill the probe child, salvage its stderr, and abort the gate."""
    try:
        proc.kill()
        proc.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        err = (proc.stderr.read() or "").strip()
    except (OSError, ValueError):
        err = ""
    die(msg + (f" | stderr tail: {err[-500:]}" if err else ""))


def probe_registry_entry() -> None:
    """Spawn the crosslab entry EXACTLY as a harness reads it and handshake.

    Reads command+args back out of the live Freebuff registry (not the
    intended ones), so the file itself is the contract under test, then runs
    initialize + tools/list over stdio. Fail-closed: a dead launch contract
    aborts the sync instead of surfacing later as "Connection closed".
    """
    step("launch probe: spawning the written registry entry over stdio")
    data, _bom, _crlf = _read_json(SERVERS["freebuff"]["path"])
    entry = (data.get("mcpServers") or {}).get(ENTRY_NAME) or {}
    cmd = entry.get("command")
    argv = list(entry.get("args") or [])
    if not cmd:
        die("probe: freebuff registry has no crosslab entry")
    print("  $ " + " ".join([cmd, *argv]))
    env = dict(os.environ)
    env.update(entry.get("env") or {})
    proc = subprocess.Popen(
        [cmd, *argv],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", env=env,
    )

    def send(obj: dict) -> None:
        try:
            proc.stdin.write(json.dumps(obj) + "\n")
            proc.stdin.flush()
        except (OSError, ValueError):
            _probe_fail(proc, "probe: server closed stdin before the handshake")

    def await_id(want: int, deadline_s: float = 90.0) -> dict:
        end = time.time() + deadline_s
        while time.time() < end:
            line = proc.stdout.readline()
            if not line:
                _probe_fail(proc, f"probe: server exited before replying to id={want}")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # stray non-protocol line; only JSON replies count
            if msg.get("id") == want:
                return msg
        _probe_fail(proc, f"probe: timed out waiting for id={want}")

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                         "clientInfo": {"name": "crosslab_sync", "version": "0"}}})
        init = await_id(1)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        listing = await_id(2)
    finally:
        try:
            proc.kill()
            proc.wait(timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            pass
    if "error" in init:
        die(f"probe: initialize errored: {init['error']}")
    tools = (listing.get("result") or {}).get("tools") or []
    if not tools:
        die("probe: handshake completed but tools/list returned no tools")
    server_name = ((init.get("result") or {}).get("serverInfo") or {}).get("name", "?")
    print(f"  [ok] {server_name} answered; {len(tools)} tools visible over stdio")


# Single-flight guard for the whole pipeline — the post-commit hook runs the
# sync detached, so a manual run (or a second quick commit's hook) must not
# race it: two `--force` reinstalls fight over the same tool env. mkdir is
# atomic on Windows; a lock older than STALE_SECONDS is stolen (crashed run).
LOCK_DIR = Path.home() / ".crosslab.sync-lock"
LOCK_STALE_SECONDS = 900


def _acquire_lock() -> bool:
    try:
        LOCK_DIR.mkdir()
        return True
    except FileExistsError:
        pass
    try:
        stale = time.time() - LOCK_DIR.stat().st_mtime > LOCK_STALE_SECONDS
    except OSError:
        return False
    if not stale:
        return False
    shutil.rmtree(LOCK_DIR, ignore_errors=True)
    try:
        LOCK_DIR.mkdir()
        return True
    except FileExistsError:
        return False


def ensure_hook_config() -> None:
    """Point this clone's core.hooksPath at the tracked hooks/ directory.

    Git never clones config, so a fresh clone fires no post-commit hook even
    with hooks/post-commit tracked. But crosslab_sync.py runs once right
    after cloning anyway (the registry tier must point this machine's
    harnesses at the shim), so it can self-heal the config: auto-sync then
    holds on every later commit with no manual setup step.
    """
    step("hooks tier: core.hooksPath -> hooks")
    probe = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=str(REPO), capture_output=True, text=True,
    )
    if probe.returncode == 0 and probe.stdout.strip() == "hooks":
        print("  [ok] current")
        return
    r = subprocess.run(["git", "config", "core.hooksPath", "hooks"], cwd=str(REPO))
    if r.returncode != 0:
        print("  WARNING: could not set core.hooksPath — auto-sync stays off "
              "until `git config core.hooksPath hooks` succeeds")
        return
    print("  [ok] set (post-commit auto-sync active for this clone)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="no writes; plan only")
    ap.add_argument("--skip-tests", action="store_true",
                    help="skip the test gate (defeats the point; use knowingly)")
    ap.add_argument("--only", choices=sorted(SERVERS) + sorted(TOML_SERVERS),
                    help="sync one harness only")
    args = ap.parse_args()

    if not _acquire_lock():
        print("[sync] another crosslab_sync is already running — exiting (nothing broken)")
        return
    t0 = time.time()
    try:
        step("crosslab propagation (local checkout; nothing published)")
        if not args.skip_tests:
            run_tests()
        else:
            print("[sync] WARNING --skip-tests: propagating untested code")
        refresh_env(args.dry_run)
        for name, spec in SERVERS.items():
            if args.only and name != args.only:
                continue
            sync_registry(name, spec, args.dry_run)
        for name, spec in TOML_SERVERS.items():
            if args.only and name != args.only:
                continue
            sync_codex_toml(name, spec, args.dry_run)
        if not args.dry_run:
            probe_registry_entry()
            ensure_hook_config()
    finally:
        shutil.rmtree(LOCK_DIR, ignore_errors=True)
    step(f"done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
