"""Personal model connections through the providers' own signed-in runtimes.

Never borrow the server operator's login or turn subscription credentials into
API keys. Each studio user/account pair has a private runtime configuration.
"""
from __future__ import annotations

import atexit
import base64
import hashlib
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path

SESSIONS_ROOT = Path(__file__).resolve().parent.parent / "data/model_sessions"
_POOL: dict[str, CodexSession] = {}
_POOL_LOCK = threading.Lock()


class ConnectionUnavailable(RuntimeError):
    pass


def scope_id(user_id: str, account_id: int) -> str:
    if not user_id or account_id is None:
        raise ConnectionUnavailable("Sign into a studio account first.")
    return hashlib.sha256(json.dumps([str(user_id), int(account_id)]).encode()).hexdigest()


def executable(provider: str) -> str | None:
    name = {"chatgpt": "codex", "claude": "claude"}.get(provider)
    if not name:
        raise ConnectionUnavailable("Unknown personal model provider.")
    return shutil.which(name)


def runtime_dir(scope: str, provider: str) -> Path:
    root = SESSIONS_ROOT / scope / provider
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    root.parent.chmod(0o700)
    SESSIONS_ROOT.chmod(0o700)
    return root


def runtime_env(root: Path, provider: str) -> dict:
    # Allowlist: never inherit API keys, OAuth tokens, MCP settings, or the
    # desktop agent's active-session environment from this server process.
    env = {k: os.environ[k] for k in ("PATH", "HOME", "USER", "LANG", "TMPDIR",
                                     "SYSTEMROOT") if k in os.environ}
    env["CODEX_HOME" if provider == "chatgpt" else "CLAUDE_CONFIG_DIR"] = str(root)
    return env


class CodexSession:
    """One private, stdio-only app-server; responses are never logged."""

    def __init__(self, scope):
        binary = executable("chatgpt")
        if not binary:
            raise ConnectionUnavailable("Codex must be installed on the studio server to connect ChatGPT.")
        self.root = runtime_dir(scope, "chatgpt")
        self.workspace = self.root / "workspace"
        self.workspace.mkdir(exist_ok=True, mode=0o700)
        self.last_used = time.monotonic()
        self.lock = threading.Lock()
        self.turn_lock = threading.Lock()
        self.pending = {}
        self.events = queue.Queue()
        self.counter = 0
        self.login = None
        self.login_id = None
        self.auth_lock = threading.Lock()
        self.login_error = ""
        # This is a creative conversation, with no shell, plugins, browser,
        # MCP, or filesystem tools. The unmodified runtime handles OAuth.
        config = {
            "cli_auth_credentials_store": "file", "forced_login_method": "chatgpt",
            "web_search": "disabled", "sandbox_mode": "read-only",
            "approval_policy": "never", "mcp_servers": {},
            "features": {name: False for name in (
                "shell_tool", "unified_exec", "apps", "plugins", "hooks",
                "browser_use", "computer_use", "code_mode", "code_mode_host",
                "multi_agent", "image_generation", "view_image", "sleep_tool",
                "goals", "tool_suggest", "workspace_dependencies", "memories")},
        }
        config["features"]["skip_host_skill_discovery"] = True
        # JSON objects aren't TOML inline tables; pass each leaf override.
        args = [binary, "app-server", "--listen", "stdio://"]
        for key, value in config.items():
            if key == "features":
                for feature, enabled in value.items():
                    args.extend(["-c", f"features.{feature}={str(enabled).lower()}"])
            else:
                args.extend(["-c", f"{key}=" + ("{}" if value == {} else json.dumps(value))])
        self.process = subprocess.Popen(args, cwd=self.workspace,
            env=runtime_env(self.root, "chatgpt"), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()
        try:
            self.call("initialize", {"clientInfo": {"name": "zeropage_studio",
                "title": "Zero Page Films Studio", "version": "1.0"}})
            self._send({"method": "initialized", "params": {}})
        except Exception:
            self.close()
            raise

    def _send(self, message):
        with self.lock:
            if self.process.poll() is not None:
                raise ConnectionUnavailable("The ChatGPT connection stopped. Reconnect and try again.")
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()

    def _read(self):
        try:
            for line in self.process.stdout:
                message = json.loads(line)
                if "method" in message and "id" in message:
                    # Never approve a tool/action requested by the runtime.
                    self._send({"id": message["id"], "error": {
                        "code": -32601, "message": "This studio connection supports conversation only."}})
                elif "id" in message:
                    target = self.pending.get(message["id"])
                    if target:
                        target.put(message)
                else:
                    if message.get("method") == "account/login/completed":
                        self.login = None
                        self.login_id = None
                        self.login_error = "" if message.get("params", {}).get("success") else (
                            "Sign-in did not complete. Please try again.")
                    if message.get("method") in ("turn/completed", "item/completed"):
                        self.events.put(message)
        finally:
            for target in list(self.pending.values()):
                target.put({"error": {"message": "Model connection closed."}})

    def call(self, method, params=None, timeout=30):
        self.last_used = time.monotonic()
        with self.lock:
            self.counter += 1
            request_id = self.counter
            target = self.pending[request_id] = queue.Queue()
        try:
            self._send({"id": request_id, "method": method, "params": params or {}})
            response = target.get(timeout=timeout)
            if "error" in response:
                # Runtime errors may contain URLs or credentials. Keep raw
                # protocol output out of the HTTP response and jobs registry.
                raise ConnectionUnavailable(
                    f"ChatGPT could not complete {method}. Reconnect or check your plan limits.")
            return response.get("result", {})
        except queue.Empty:
            raise ConnectionUnavailable("ChatGPT took too long to respond. Try again.") from None
        finally:
            self.pending.pop(request_id, None)

    def status(self):
        account = self.call("account/read", {"refreshToken": False}).get("account") or {}
        connected = account.get("type") == "chatgpt"
        return {"available": True, "connected": connected,
                "plan": account.get("planType") if connected else None,
                "login": self.login, "message": self.login_error,
                "billing": "Uses your ChatGPT plan's Codex allowance."}

    def start_login(self):
        with self.auth_lock:
            if self.turn_lock.locked():
                raise ConnectionUnavailable("Wait for your current reply before changing the connection.")
            if self.login:
                return self.login
            result = self.call("account/login/start", {"type": "chatgptDeviceCode"}, timeout=45)
            # Forward only the provider's user-facing device challenge.
            self.login_id = result.get("loginId")
            self.login = {"url": result["verificationUrl"], "code": result["userCode"]}
            self.login_error = ""
            return self.login

    def logout(self):
        with self.auth_lock:
            if self.login_id:
                self.call("account/login/cancel", {"loginId": self.login_id})
                self.login_id = None
            self.call("account/logout")
            self.login = None

    def models(self):
        result = self.call("model/list", {"limit": 100, "includeHidden": False})
        return [{"id": m["model"], "label": m["displayName"],
                 "default": m.get("isDefault", False)} for m in result.get("data", [])]

    def generate(self, prompt, instruction, schema, images, model=""):
        if not self.turn_lock.acquire(blocking=False):
            raise ConnectionUnavailable("Your ChatGPT guide is already responding. Wait for that reply.")
        thread_id = None
        try:
            if not self.status()["connected"]:
                raise ConnectionUnavailable("Connect your ChatGPT account first.")
            models = self.models()
            if model and model not in {m["id"] for m in models}:
                raise ConnectionUnavailable("That model is not available on your ChatGPT connection.")
            started = self.call("thread/start", {
                "cwd": str(self.workspace), "sandbox": "read-only", "approvalPolicy": "never",
                "ephemeral": True, "baseInstructions": instruction,
                **({"model": model} if model else {})})
            thread_id = started["thread"]["id"]
            inputs = [{"type": "text", "text": prompt}]
            for raw, mime, label in images:
                inputs.extend([{"type": "text", "text": label or "Reference image"},
                    {"type": "image", "url": f"data:{mime};base64,{base64.b64encode(raw).decode()}"}])
            turn = self.call("turn/start", {"threadId": thread_id, "input": inputs,
                                          "outputSchema": schema})["turn"]["id"]
            deadline = time.monotonic() + 240
            answer = ""
            while time.monotonic() < deadline:
                try:
                    event = self.events.get(timeout=max(.1, deadline - time.monotonic()))
                except queue.Empty:
                    break
                data = event.get("params", {})
                if data.get("threadId") != thread_id:
                    continue
                if event["method"] == "item/completed":
                    item = data.get("item", {})
                    if item.get("type") == "agentMessage":
                        answer = item.get("text", "")
                elif event["method"] == "turn/completed":
                    if data.get("turn", {}).get("status") != "completed":
                        raise ConnectionUnavailable(
                            "ChatGPT did not finish the reply. Check your connection or plan limits.")
                    if not answer:
                        raise ConnectionUnavailable("ChatGPT returned no scene brief.")
                    return answer
            self.call("turn/interrupt", {"threadId": thread_id, "turnId": turn})
            raise ConnectionUnavailable("ChatGPT timed out. Your conversation has been kept for retry.")
        finally:
            if thread_id:
                try:
                    self.call("thread/unsubscribe", {"threadId": thread_id}, timeout=5)
                except ConnectionUnavailable:
                    pass
            self.turn_lock.release()

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)


def codex_session(scope):
    with _POOL_LOCK:
        old = _POOL.get(scope)
        if old and old.process.poll() is None:
            return old
        _POOL.pop(scope, None)
        # Reap inactive runtimes and bound resource use on a shared server.
        for key, inactive in list(_POOL.items()):
            if time.monotonic() - inactive.last_used > 1200 and not inactive.turn_lock.locked():
                inactive.close()
                del _POOL[key]
        if len(_POOL) >= 4:
            raise ConnectionUnavailable("Personal model connections are busy. Try again shortly.")
        session = CodexSession(scope)
        _POOL[scope] = session
        return session


def close_all():
    with _POOL_LOCK:
        for session in _POOL.values():
            session.close()
        _POOL.clear()
    with _CLAUDE_LOCK:
        for login in _CLAUDE_LOGINS.values():
            if login.poll() is None:
                login.terminate()
        _CLAUDE_LOGINS.clear()


atexit.register(close_all)

_CLAUDE_LOGINS: dict[str, subprocess.Popen] = {}
_CLAUDE_LOCK = threading.Lock()
_CLAUDE_TURNS: dict[str, threading.Lock] = {}
CLAUDE_MODELS = [
    {"id": "sonnet", "label": "Claude Sonnet", "default": True},
    {"id": "opus", "label": "Claude Opus", "default": False},
    {"id": "haiku", "label": "Claude Haiku", "default": False},
]


def claude_command(scope, args, *, input=None, timeout=20):
    binary = executable("claude")
    if not binary:
        raise ConnectionUnavailable("Claude Code must be installed on the studio computer.")
    root = runtime_dir(scope, "claude")
    try:
        return subprocess.run([binary, *args], input=input, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=root,
            env=runtime_env(root, "claude"), timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ConnectionUnavailable("Claude took too long to respond. Please try again.") from None


def claude_status(scope):
    result = claude_command(scope, ["auth", "status", "--json"])
    try:
        data = json.loads(result.stdout)
    except ValueError:
        raise ConnectionUnavailable("Unable to read the Claude connection. Please reconnect.") from None
    connected = bool(data.get("loggedIn")) and data.get("authMethod") == "claude.ai"
    with _CLAUDE_LOCK:
        login = _CLAUDE_LOGINS.get(scope)
        if login and login.poll() is not None:
            _CLAUDE_LOGINS.pop(scope, None)
            login = None
    return {"available": True, "connected": connected, "login": bool(login),
            "billing": "Uses your own Claude plan, subject to its usage limits.",
            "message": "Finish signing in in the browser opened by Claude Code." if login else ""}


def claude_login(scope):
    # Caller must verify browser and runtime are on the same machine. The
    # unmodified CLI owns its localhost callback; no auth code/token passes
    # through our HTTP API, and no custom Claude OAuth client is invented.
    root = runtime_dir(scope, "claude")
    binary = executable("claude")
    if not binary:
        raise ConnectionUnavailable("Claude Code must be installed on the studio computer.")
    with _CLAUDE_LOCK:
        existing = _CLAUDE_LOGINS.get(scope)
        if not existing or existing.poll() is not None:
            process = subprocess.Popen([binary, "auth", "login"], cwd=root,
                env=runtime_env(root, "claude"), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _CLAUDE_LOGINS[scope] = process

            def expire():
                try:
                    process.wait(timeout=300)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=5)
            threading.Thread(target=expire, daemon=True).start()
    return {"message": "Claude Code opened its sign-in page on this computer. "
                       "Complete that sign-in, then refresh connection status."}


def disconnect(scope, provider):
    if provider == "chatgpt":
        session = codex_session(scope)
        if not session.turn_lock.acquire(blocking=False):
            raise ConnectionUnavailable("Wait for your current reply before disconnecting.")
        try:
            session.logout()
        finally:
            session.turn_lock.release()
    elif provider == "claude":
        with _CLAUDE_LOCK:
            lock = _CLAUDE_TURNS.setdefault(scope, threading.Lock())
        if not lock.acquire(blocking=False):
            raise ConnectionUnavailable("Wait for your current reply before disconnecting.")
        try:
            with _CLAUDE_LOCK:
                login = _CLAUDE_LOGINS.pop(scope, None)
                if login and login.poll() is None:
                    login.terminate()
                    login.wait(timeout=5)
            result = claude_command(scope, ["auth", "logout"])
            if result.returncode:
                raise ConnectionUnavailable("Claude could not disconnect. Try again.")
        finally:
            lock.release()
    else:
        raise ConnectionUnavailable("Unknown personal model provider.")


def claude_generate(scope, prompt, instruction, schema, images, model=""):
    if model and model not in {m["id"] for m in CLAUDE_MODELS}:
        raise ConnectionUnavailable("Choose one of the listed Claude models.")
    with _CLAUDE_LOCK:
        lock = _CLAUDE_TURNS.setdefault(scope, threading.Lock())
    if not lock.acquire(blocking=False):
        raise ConnectionUnavailable("Your Claude guide is already responding. Wait for that reply.")
    try:
        if not claude_status(scope)["connected"]:
            raise ConnectionUnavailable("Connect your own Claude account first.")
        content = [{"type": "text", "text": prompt}]
        for raw, mime, label in images:
            content.extend([{"type": "text", "text": label or "Reference image"},
                {"type": "image", "source": {"type": "base64", "media_type": mime,
                                                "data": base64.b64encode(raw).decode()}}])
        payload = json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"
        result = claude_command(scope, ["--print", "--input-format", "stream-json",
            "--output-format", "json", "--json-schema", json.dumps(schema),
            "--system-prompt", instruction, "--model", model or "sonnet",
            "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--disable-slash-commands", "--no-chrome", "--no-session-persistence",
            "--setting-sources", "", "--safe-mode"], input=payload, timeout=240)
        try:
            data = json.loads(result.stdout)
        except ValueError:
            raise ConnectionUnavailable(
                "Claude returned no usable reply. Check your sign-in and plan limits.") from None
        if result.returncode or data.get("is_error"):
            raise ConnectionUnavailable("Claude could not finish. Check your connection and plan limits.")
        structured = data.get("structured_output")
        return json.dumps(structured) if structured else data.get("result", "")
    finally:
        lock.release()
