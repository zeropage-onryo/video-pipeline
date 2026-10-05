#!/usr/bin/env python3
"""
Supabase Auth's email settings, from the command line: what is set, and
the whole 2026-10-03 setup applied in one go (custom SMTP, the four
templates under ops/email_templates/, the Site URL, the hourly send
limit). The dashboard has no API this app holds a key for, so this talks
to Supabase's Management API with a PERSONAL ACCESS TOKEN -- make one at
https://supabase.com/dashboard/account/tokens and export it as
SUPABASE_ACCESS_TOKEN (or type it when asked; it is never printed).

    python -m ops.supabase_auth_email report
    python -m ops.supabase_auth_email apply --templates [--dry-run]
    python -m ops.supabase_auth_email apply --templates \\
        --smtp-host smtp.resend.com --smtp-port 465 --smtp-user resend \\
        --sender-email no-reply@zeropage.studio --sender-name "Zero Page" \\
        --site-url https://zeropage-studio.fly.dev --rate-limit 100
    SMTP_PASS=... python -m ops.supabase_auth_email apply --smtp-host ...

The project is read off SUPABASE_URL (https://<ref>.supabase.co) or
--project. `report` is read-only. `apply` sends ONE PATCH carrying only
what you asked for -- flags you leave out are not touched -- and refuses
any field the live config does not already carry, so a renamed setting
fails before the write rather than being silently dropped. --dry-run
prints the body with the password redacted and sends nothing.

Why each piece (docs/SUPABASE_EMAIL_TEMPLATES.md says it at length):
Supabase's built-in mailer delivers only to the organisation's own team,
so a stranger gets nothing until custom SMTP is on; the default templates
carry only a PKCE link, which fails in a mail app's browser, so these
carry the 6-digit {{ .Token }} to type and a {{ .TokenHash }} link into
this app's /auth/confirm that works anywhere; and the Site URL is where
that link lands, so it must be the API's origin.
"""
import argparse
import getpass
import json
import os
import re
import sys
from pathlib import Path
from typing import Callable, Optional

import requests

API = "https://api.supabase.com/v1/projects/{ref}/config/auth"
TEMPLATES_DIR = Path(__file__).resolve().parent / "email_templates"

# template file -> (content field, subject field, subject)
TEMPLATES = {
    "confirmation": ("mailer_templates_confirmation_content",
                     "mailer_subjects_confirmation", "Your Zero Page code"),
    "magic_link": ("mailer_templates_magic_link_content",
                   "mailer_subjects_magic_link", "Your Zero Page sign-in code"),
    "recovery": ("mailer_templates_recovery_content",
                 "mailer_subjects_recovery", "Reset your Zero Page password"),
    "email_change": ("mailer_templates_email_change_content",
                     "mailer_subjects_email_change", "Confirm your new Zero Page email"),
}
SMTP_FIELDS = ("smtp_host", "smtp_port", "smtp_user", "smtp_pass",
               "smtp_admin_email", "smtp_sender_name")
SECRET_FIELDS = ("smtp_pass",)
REDACTED = "<redacted>"


def project_ref(explicit: Optional[str] = None,
                env: Optional[dict] = None) -> Optional[str]:
    """--project, else the <ref> in SUPABASE_URL."""
    if explicit:
        return explicit
    url = (env if env is not None else os.environ).get("SUPABASE_URL") or ""
    found = re.match(r"https?://([a-z0-9-]+)\.supabase\.co", url.strip())
    return found.group(1) if found else None


def access_token(ask: Callable = getpass.getpass, env: Optional[dict] = None) -> str:
    token = (env if env is not None else os.environ).get("SUPABASE_ACCESS_TOKEN") or ""
    return token.strip() or ask("Supabase personal access token: ").strip()


def load_templates(directory: Path = TEMPLATES_DIR) -> dict:
    """The four bodies and their subjects, as PATCH fields. Each body is
    checked for the two things the pages depend on before it is sent."""
    fields = {}
    for name, (content_key, subject_key, subject) in TEMPLATES.items():
        body = (directory / f"{name}.html").read_text()
        if name != "email_change" and "{{ .Token }}" not in body:
            raise ValueError(f"{name}.html carries no {{{{ .Token }}}} -- the pages ask for a code")
        if "/auth/confirm?token_hash={{ .TokenHash }}" not in body:
            raise ValueError(f"{name}.html carries no /auth/confirm token_hash link")
        fields[content_key] = body
        fields[subject_key] = subject
    return fields


def redact(body: dict) -> dict:
    return {k: (REDACTED if k in SECRET_FIELDS and v else v) for k, v in body.items()}


def fetch(ref: str, token: str, request: Callable = requests.request) -> dict:
    response = request("GET", API.format(ref=ref), headers=_headers(token), timeout=20)
    if response.status_code >= 400:
        raise RuntimeError(f"GET auth config: HTTP {response.status_code}: "
                           f"{_safe_text(response)}")
    return response.json()


def patch(ref: str, token: str, body: dict,
          request: Callable = requests.request) -> dict:
    response = request("PATCH", API.format(ref=ref), headers=_headers(token),
                       json=body, timeout=30)
    if response.status_code >= 400:
        raise RuntimeError(f"PATCH auth config: HTTP {response.status_code}: "
                           f"{_safe_text(response)}")
    return response.json()


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _safe_text(response) -> str:
    try:
        return (response.text or "")[:300]
    except Exception:  # noqa: BLE001
        return ""


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def describe(config: dict) -> list[str]:
    """The settings that decide whether a new person gets an email, as
    lines. Never the password."""
    lines = []
    host = config.get("smtp_host") or ""
    if host:
        lines.append(f"SMTP: custom -- {host}:{config.get('smtp_port') or '?'} as "
                     f"{config.get('smtp_user') or '?'}, from "
                     f"{config.get('smtp_sender_name') or '?'} "
                     f"<{config.get('smtp_admin_email') or '?'}>")
    else:
        lines.append("SMTP: NOT SET -- Supabase's built-in mailer, which delivers only "
                     "to the organisation's own team members")
    provider = "on" if config.get("external_email_enabled", True) else "OFF"
    confirm = "off (session at once)" if config.get("mailer_autoconfirm") else "on (must click first)"
    secure = "on" if config.get("mailer_secure_email_change_enabled", True) else "off"
    lines.append(f"email provider: {provider} | confirm email: {confirm} | "
                 f"secure email change: {secure}")
    lines.append(f"site url: {config.get('site_url') or '(unset)'}")
    allow = config.get("uri_allow_list") or ""
    lines.append(f"redirect allow-list: {allow or '(empty)'}")
    lines.append(f"email send limit: {config.get('rate_limit_email_sent', '?')}/hour")
    for name, (content_key, subject_key, _) in TEMPLATES.items():
        body = config.get(content_key) or ""
        marks = []
        marks.append("code" if "{{ .Token }}" in body else ("-" if name == "email_change" else "NO CODE"))
        marks.append("confirm-link" if "/auth/confirm" in body
                     else ("pkce-link" if "ConfirmationURL" in body else "no link"))
        state = "default" if not body else ", ".join(marks)
        lines.append(f"template {name:13s}: {state}  subject: {config.get(subject_key) or '(default)'}")
    return lines


def cmd_report(args, *, request=requests.request, ask=getpass.getpass) -> int:
    ref = project_ref(args.project)
    if not ref:
        print("no project: pass --project <ref> or export SUPABASE_URL", file=sys.stderr)
        return 2
    config = fetch(ref, access_token(ask), request=request)
    print(f"project {ref}")
    for line in describe(config):
        print("  " + line)
    return 0


# --------------------------------------------------------------------------
# apply
# --------------------------------------------------------------------------

def build_body(args, *, templates_dir: Path = TEMPLATES_DIR,
               smtp_pass: Optional[str] = None) -> dict:
    """What the flags ask for, and nothing else."""
    body: dict = {}
    if args.templates:
        body.update(load_templates(templates_dir))
    if args.smtp_host:
        missing = [f for f, v in (("--smtp-port", args.smtp_port), ("--smtp-user", args.smtp_user),
                                  ("--sender-email", args.sender_email)) if not v]
        if missing:
            raise ValueError("custom SMTP needs " + ", ".join(missing))
        if not smtp_pass:
            raise ValueError("custom SMTP needs the password: SMTP_PASS=... or type it")
        # smtp_port goes over the wire as a STRING: the Management API answers
        # HTTP 400 "expected string, received number" to an int (2026-10-05).
        body.update({"smtp_host": args.smtp_host, "smtp_port": str(int(args.smtp_port)),
                     "smtp_user": args.smtp_user, "smtp_pass": smtp_pass,
                     "smtp_admin_email": args.sender_email,
                     "smtp_sender_name": args.sender_name or "Zero Page"})
    if args.site_url:
        body["site_url"] = args.site_url.rstrip("/")
    if args.allow:
        body["uri_allow_list"] = ",".join(u.strip() for u in args.allow if u.strip())
    if args.rate_limit is not None:
        body["rate_limit_email_sent"] = int(args.rate_limit)
    if not body:
        raise ValueError("nothing to apply: pass --templates, --smtp-host, --site-url, "
                         "--allow or --rate-limit")
    return body


def unknown_fields(body: dict, live: dict) -> list[str]:
    """Fields the live config does not carry -- a renamed setting, which
    the API might accept and ignore. Refused rather than guessed."""
    return sorted(k for k in body if k not in live)


def cmd_apply(args, *, request=requests.request, ask=getpass.getpass,
              env: Optional[dict] = None) -> int:
    env = os.environ if env is None else env
    ref = project_ref(args.project, env)
    if not ref:
        print("no project: pass --project <ref> or export SUPABASE_URL", file=sys.stderr)
        return 2
    smtp_pass = env.get("SMTP_PASS") or ""
    if args.smtp_host and not smtp_pass and not args.dry_run:
        smtp_pass = ask("SMTP password: ")
    try:
        body = build_body(args, smtp_pass=smtp_pass or ("x" if args.dry_run else ""))
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    if args.dry_run:
        print(f"would PATCH project {ref} with:")
        print(json.dumps(redact(body), indent=2))
        return 0
    token = access_token(ask, env)
    live = fetch(ref, token, request=request)
    bad = unknown_fields(body, live)
    if bad:
        print("refused: the live auth config carries no field named "
              + ", ".join(bad) + " -- Supabase may have renamed it; check "
              "https://api.supabase.com/api/v1#tag/auth/PATCH/v1/projects/{ref}/config/auth",
              file=sys.stderr)
        return 2
    patch(ref, token, body, request=request)
    print(f"applied to project {ref}: " + ", ".join(sorted(redact(body))))
    after = fetch(ref, token, request=request)
    for line in describe(after):
        print("  " + line)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="supabase_auth_email",
                                     description=__doc__.split("\n\n")[0])
    parser.add_argument("--project", help="the project ref (default: from SUPABASE_URL)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("report", help="what is set (read-only, never the password)")
    ap = sub.add_parser("apply", help="set what the flags name, in one PATCH")
    ap.add_argument("--templates", action="store_true",
                    help="the four bodies + subjects from ops/email_templates/")
    ap.add_argument("--smtp-host")
    ap.add_argument("--smtp-port")
    ap.add_argument("--smtp-user")
    ap.add_argument("--sender-email", help="the From address (smtp_admin_email)")
    ap.add_argument("--sender-name", help="the From name (default Zero Page)")
    ap.add_argument("--site-url", help="the API origin, where /auth/confirm lives")
    ap.add_argument("--allow", action="append",
                    help="a redirect allow-list entry (repeatable; replaces the list)")
    ap.add_argument("--rate-limit", help="emails per hour (rate_limit_email_sent)")
    ap.add_argument("--dry-run", action="store_true", help="print the body, send nothing")
    args = parser.parse_args(argv)
    try:
        if args.command == "report":
            return cmd_report(args)
        return cmd_apply(args)
    except (RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
