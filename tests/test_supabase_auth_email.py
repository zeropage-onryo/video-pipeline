"""ops/supabase_auth_email.py: the Management API door onto Supabase
Auth's email settings. Every HTTP call is a stub `request`; nothing
reaches the network, and no assertion may find the SMTP password or the
access token in anything printed."""
import json
from types import SimpleNamespace

import pytest

from ops import supabase_auth_email as sae

TOKEN = "sbp-very-secret-access-token"
SMTP_PASS = "re_super_secret_smtp_password"


class Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


def stub_request(live: dict, patch_status: int = 200):
    calls = []

    def request(method, url, headers=None, json=None, timeout=None):
        calls.append((method, url, headers, json))
        if method == "GET":
            return Resp(200, live)
        if method == "PATCH":
            if patch_status >= 400:
                return Resp(patch_status, {"message": "bad request"})
            live.update(json)
            return Resp(200, live)
        raise AssertionError(method)
    request.calls = calls
    return request


LIVE = {"smtp_host": "", "smtp_port": None, "smtp_user": "", "smtp_pass": "",
        "smtp_admin_email": "", "smtp_sender_name": "", "site_url": "http://localhost:3000",
        "uri_allow_list": "", "rate_limit_email_sent": 2, "external_email_enabled": True,
        "mailer_autoconfirm": False, "mailer_secure_email_change_enabled": True,
        **{sae.TEMPLATES[n][0]: "<p>{{ .ConfirmationURL }}</p>" for n in sae.TEMPLATES},
        **{sae.TEMPLATES[n][1]: "" for n in sae.TEMPLATES}}


def args(**over):
    base = dict(project="abcdefghijklmnop", templates=False, smtp_host=None, smtp_port=None,
                smtp_user=None, sender_email=None, sender_name=None, site_url=None,
                allow=None, rate_limit=None, dry_run=False)
    base.update(over)
    return SimpleNamespace(**base)


def test_the_project_ref_comes_off_supabase_url():
    assert sae.project_ref(None, {"SUPABASE_URL": "https://ewkbrenbjsiggufegrnd.supabase.co"}) \
        == "ewkbrenbjsiggufegrnd"
    assert sae.project_ref("explicit", {"SUPABASE_URL": "https://x.supabase.co"}) == "explicit"
    assert sae.project_ref(None, {}) is None


def test_the_shipped_templates_carry_a_code_and_a_confirm_link():
    fields = sae.load_templates()
    assert len(fields) == 8
    for name, (content_key, subject_key, subject) in sae.TEMPLATES.items():
        body = fields[content_key]
        assert "/auth/confirm?token_hash={{ .TokenHash }}" in body
        assert fields[subject_key] == subject
        if name != "email_change":
            assert "{{ .Token }}" in body
    assert "type=recovery" in fields["mailer_templates_recovery_content"]
    assert "type=email_change" in fields["mailer_templates_email_change_content"]


def test_a_template_without_the_code_is_refused(tmp_path):
    for name in sae.TEMPLATES:
        (tmp_path / f"{name}.html").write_text(
            '<a href="{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=email">x</a>')
    with pytest.raises(ValueError, match="Token"):
        sae.load_templates(tmp_path)


def test_report_reads_the_live_config_and_never_prints_the_password(capsys):
    live = dict(LIVE, smtp_host="smtp.resend.com", smtp_port=465, smtp_user="resend",
                smtp_pass=SMTP_PASS, smtp_admin_email="no-reply@zeropage.studio")
    code = sae.cmd_report(args(), request=stub_request(live), ask=lambda _: TOKEN)
    out = capsys.readouterr().out
    assert code == 0
    assert "smtp.resend.com:465" in out and "NO CODE" in out and "pkce-link" in out
    assert "2/hour" in out
    assert SMTP_PASS not in out and TOKEN not in out


def test_report_says_when_the_built_in_mailer_is_still_on(capsys):
    sae.cmd_report(args(), request=stub_request(dict(LIVE)), ask=lambda _: TOKEN)
    assert "NOT SET" in capsys.readouterr().out


def test_apply_sends_one_patch_with_exactly_what_was_asked(capsys):
    live = dict(LIVE)
    request = stub_request(live)
    code = sae.cmd_apply(
        args(templates=True, smtp_host="smtp.resend.com", smtp_port="465", smtp_user="resend",
             sender_email="no-reply@zeropage.studio", sender_name="Zero Page",
             site_url="https://zeropage-studio.fly.dev/", rate_limit="100",
             allow=["https://zeropage-studio.fly.dev/auth/callback",
                    "http://localhost:8000/auth/callback"]),
        request=request, ask=lambda _: TOKEN,
        env={"SUPABASE_ACCESS_TOKEN": TOKEN, "SMTP_PASS": SMTP_PASS})
    assert code == 0, capsys.readouterr()
    methods = [c[0] for c in request.calls]
    assert methods == ["GET", "PATCH", "GET"]
    _, url, headers, body = request.calls[1]
    assert url.endswith("/projects/abcdefghijklmnop/config/auth")
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert body["smtp_host"] == "smtp.resend.com" and body["smtp_port"] == 465
    assert body["smtp_pass"] == SMTP_PASS
    assert body["site_url"] == "https://zeropage-studio.fly.dev"      # no trailing slash
    assert body["rate_limit_email_sent"] == 100
    assert body["uri_allow_list"] == ("https://zeropage-studio.fly.dev/auth/callback,"
                                      "http://localhost:8000/auth/callback")
    assert "{{ .Token }}" in body["mailer_templates_magic_link_content"]
    assert "mailer_autoconfirm" not in body                           # not asked for
    out = capsys.readouterr().out
    assert "applied" in out and "custom -- smtp.resend.com" in out
    assert SMTP_PASS not in out and TOKEN not in out


def test_dry_run_prints_a_redacted_body_and_sends_nothing(capsys):
    request = stub_request(dict(LIVE))
    code = sae.cmd_apply(
        args(templates=True, smtp_host="smtp.resend.com", smtp_port="465", smtp_user="resend",
             sender_email="no-reply@zeropage.studio", dry_run=True),
        request=request, ask=lambda _: TOKEN, env={"SMTP_PASS": SMTP_PASS})
    out = capsys.readouterr().out
    assert code == 0 and request.calls == []
    assert "would PATCH" in out and sae.REDACTED in out and SMTP_PASS not in out


def test_a_renamed_field_is_refused_before_the_write(capsys):
    live = {k: v for k, v in LIVE.items() if k != "rate_limit_email_sent"}
    request = stub_request(live)
    code = sae.cmd_apply(args(rate_limit="50"), request=request, ask=lambda _: TOKEN,
                         env={"SUPABASE_ACCESS_TOKEN": TOKEN})
    assert code == 2
    assert [c[0] for c in request.calls] == ["GET"]
    assert "rate_limit_email_sent" in capsys.readouterr().err


def test_smtp_needs_its_whole_set_and_nothing_is_a_refusal(capsys):
    request = stub_request(dict(LIVE))
    assert sae.cmd_apply(args(smtp_host="smtp.resend.com"), request=request,
                         ask=lambda _: TOKEN, env={"SMTP_PASS": SMTP_PASS}) == 2
    assert "--smtp-port" in capsys.readouterr().err
    assert sae.cmd_apply(args(), request=request, ask=lambda _: TOKEN, env={}) == 2
    assert request.calls == []


def test_an_api_refusal_is_an_error_not_a_traceback(capsys):
    request = stub_request(dict(LIVE), patch_status=400)
    with pytest.raises(RuntimeError, match="HTTP 400"):
        sae.cmd_apply(args(templates=True), request=request, ask=lambda _: TOKEN,
                      env={"SUPABASE_ACCESS_TOKEN": TOKEN})


def test_the_cli_reports_a_missing_project(capsys, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    assert sae.main(["report"]) == 2
    assert "no project" in capsys.readouterr().err
