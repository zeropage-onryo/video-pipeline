# Supabase email: the three settings and the templates to paste

Written 2026-10-03, the day a new person at zeropage.studio got no code
and could not make a password. What the project's auth logs actually
showed that morning: the confirmation mail WAS sent (06:12:06, from
`noreply@mail.app.supabase.io`), the person clicked the link, GoTrue
verified it and sent them to `/auth/callback` — and no token exchange
followed. The link's PKCE verifier lives in the cookie of the browser
that asked; a link opened from a mail app's in-app browser does not have
it, and Gmail's link scanner fetched the same link seven seconds later
(`403: Email link is invalid or has expired`, from a Google address).
They got in on a second attempt. And the mail carried no CODE to type,
because the default templates only carry the link.

Three settings fix all of it. **They can be applied from the command line
in one go** (2026-10-04, `ops/supabase_auth_email.py`, through Supabase's
Management API) -- the one thing it needs from a person is a Supabase
personal access token (https://supabase.com/dashboard/account/tokens) and,
for SMTP, a mail provider's credentials:

```bash
set -a && source .env && set +a             # SUPABASE_URL names the project
export SUPABASE_ACCESS_TOKEN=sbp_...        # or type it when asked; never printed
python -m ops.supabase_auth_email report    # what is set now (read-only)
python -m ops.supabase_auth_email apply --templates --dry-run
SMTP_PASS=re_... python -m ops.supabase_auth_email apply --templates \
    --smtp-host smtp.resend.com --smtp-port 465 --smtp-user resend \
    --sender-email no-reply@zeropage.studio --sender-name "Zero Page" \
    --site-url https://api.zeropage.studio --rate-limit 100
```

The template bodies live in `ops/email_templates/` (the same four shown
below) and `report` says, per template, whether the live one carries the
code and the confirm link. The dashboard paths follow for doing it by
hand.


## 1. Custom SMTP — Authentication → Emails → SMTP Settings

Supabase's built-in sender delivers only to the Supabase organisation's
own team members, at a low hourly limit, as a development courtesy
("Email address not authorized" for anyone else). Turn on **Custom SMTP**
with a real provider — Resend or Postmark are the quickest — and a sender
on the studio's domain, e.g. `no-reply@zeropage.studio`. Until this is
on, every email door (the sign-in code, forgot-password, the settings
page's "email me a code", an email-change confirmation) works only for
org members.

## 2. The templates — Authentication → Emails → Templates (or `apply --templates`)

Each template gets BOTH: the 6-digit code to type (`{{ .Token }}`, which
is what every page asks for) and a link that works from any browser
(`{{ .TokenHash }}` into this app's `/auth/confirm`, verified server-side,
no cookie needed — not the default `{{ .ConfirmationURL }}`, which is the
PKCE link that failed above). `{{ .SiteURL }}` is the dashboard's **Site
URL** (Authentication → URL Configuration) and must be the API origin —
`https://api.zeropage.studio` since 2026-10-08 (it was
`https://zeropage-studio.fly.dev`, which Chrome flags as a lookalike of
zeropage.studio) — because `/auth/confirm` lives there.

**Confirm sign up**

```html
<h2>Confirm your email</h2>
<p>Your Zero Page code:</p>
<p style="font-size:28px;letter-spacing:.3em"><b>{{ .Token }}</b></p>
<p>Type it on the page you came from, or
<a href="{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=email">open the studio</a>.</p>
```

**Magic Link**

```html
<h2>Your sign-in code</h2>
<p style="font-size:28px;letter-spacing:.3em"><b>{{ .Token }}</b></p>
<p>Type it on the page you came from, or
<a href="{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=email">open the studio</a>.</p>
```

**Reset Password**

```html
<h2>Reset your password</h2>
<p>Your reset code:</p>
<p style="font-size:28px;letter-spacing:.3em"><b>{{ .Token }}</b></p>
<p>Enter it with your new password, or
<a href="{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=recovery">choose a new password</a>.</p>
<p>If you didn't ask for this, ignore it — nothing changes.</p>
```

**Change Email Address**

```html
<h2>Confirm your new email</h2>
<p>You asked to move your Zero Page account from {{ .Email }} to {{ .NewEmail }}.</p>
<p><a href="{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=email_change">Confirm the change</a></p>
```

(With "Secure email change" on, Supabase sends this to both addresses
and the change applies once both are clicked.)

## 3. Rate limits — Authentication → Rate Limits

The email send limit (per hour) is what `email rate limit exceeded` on
the sign-in page means. Raise it once custom SMTP is on; the built-in
sender's own cap cannot be raised.

## Also check

- Authentication → Providers → Email: "Enable Email provider" on.
  "Confirm email" decides whether a password sign-up gets a session at
  once (off) or has to click first (on; the page says so).
- Authentication → URL Configuration: the Site URL above, and the
  redirect allow-list carrying `<API origin>/auth/callback` (the OAuth
  doors) and `http://localhost:8000/auth/callback`.
