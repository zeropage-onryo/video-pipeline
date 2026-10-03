"use client";

/* Settings (2026-10-03, Mike: "Supabase didn't send a code or allow a new
   user to create a password ... we need to build out settings and
   password change etc").

   The person's own page: who they are (the name the shell shows, the
   address), the password (set a first one, or change it) and the
   workspaces they belong to. Reached from the account menus, not the
   rail.

   A password or email change has to be made AS the person against
   Supabase, and the API keeps no token of theirs -- so each write first
   re-proves them, and the page offers the two proofs the API takes: the
   current password (when they have one) or a code mailed to the address
   on file ("Email me a code"). Somebody who signed up with Google or a
   sign-in code has no current password and takes the code. Nothing here
   spends. */
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { KeyRound, Mail, Settings as SettingsIcon, UserRound, Users } from "lucide-react";
import { ApiError, signOut } from "@/lib/api";
import {
  changeEmail,
  getSecurity,
  sendSecurityCode,
  setPassword,
  switchAccount,
  updateMe,
  type Me,
  type Proof,
  type Security,
} from "@/lib/studio-api";
import { useShell } from "@/components/studio/shell";

const CARD = "rounded-xl border border-white/10 bg-white/[0.03] p-4 sm:p-5";
const BTN = "rounded-lg px-3 py-1.5 text-[13px] transition disabled:opacity-40";
const PRI = `${BTN} bg-white text-black hover:bg-white/90 disabled:bg-white/15 disabled:text-white/40 disabled:opacity-100`;
const GHOST = `${BTN} border border-white/15 text-white/80 hover:border-white/40`;
const FIELD =
  "w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-[13px] text-white/90 outline-none focus:border-white/30";
const LABEL = "mb-1 block text-[11px] uppercase tracking-wide text-white/40";
const HINT = "text-[12px] text-white/40";

const errorText = (err: unknown, fallback: string) =>
  err instanceof ApiError ? err.message : err instanceof Error ? err.message || fallback : fallback;

function SectionHead({ icon: Icon, title, sub }: { icon: typeof UserRound; title: string; sub?: string }) {
  return (
    <div className="mb-3 flex items-center gap-2">
      <Icon size={15} className="text-white/55" />
      <h2 className="text-[14px] text-white/90">{title}</h2>
      {sub ? <span className={HINT}>{sub}</span> : null}
    </div>
  );
}

/* The proof block both writes share: the current password when the
   account has one, else (or as well) a code from the inbox. */
function ProofFields({
  security,
  proof,
  onChange,
  onSendCode,
  sending,
  codeSentTo,
}: {
  security: Security;
  proof: Proof;
  onChange: (p: Proof) => void;
  onSendCode: () => void;
  sending: boolean;
  codeSentTo: string | null;
}) {
  // no password on file = the code is the only proof; with one, the
  // person picks (the password by default)
  const [pickedCode, setPickedCode] = useState(false);
  const useCode = security.has_password ? pickedCode : true;
  const setUseCode = setPickedCode;
  return (
    <div className="grid gap-2">
      {security.has_password ? (
        <div className="flex gap-3 text-[12px] text-white/50">
          <label className="flex items-center gap-1.5">
            <input type="radio" checked={!useCode} onChange={() => setUseCode(false)} />
            with my current password
          </label>
          <label className="flex items-center gap-1.5">
            <input type="radio" checked={useCode} onChange={() => setUseCode(true)} />
            with a code from my email
          </label>
        </div>
      ) : null}
      {!useCode ? (
        <div>
          <label className={LABEL}>Current password</label>
          <input
            className={FIELD}
            type="password"
            autoComplete="current-password"
            value={proof.current_password ?? ""}
            onChange={(e) => onChange({ current_password: e.target.value })}
          />
        </div>
      ) : (
        <div>
          <label className={LABEL}>Code from your email</label>
          <div className="flex gap-2">
            <input
              className={`${FIELD} max-w-[180px] tracking-[0.3em]`}
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="000000"
              maxLength={10}
              value={proof.code ?? ""}
              onChange={(e) => onChange({ code: e.target.value.replace(/\D/g, "") })}
            />
            <button type="button" className={GHOST} disabled={sending} onClick={onSendCode}>
              {sending ? "Sending…" : codeSentTo ? "Send again" : "Email me a code"}
            </button>
          </div>
          <p className={`${HINT} mt-1`}>
            {codeSentTo
              ? `Sent to ${codeSentTo} — type the 6-digit code from that email.`
              : `We’ll mail a code to ${security.email ?? "your address"} to confirm it’s you.`}
          </p>
        </div>
      )}
    </div>
  );
}

export default function SettingsPage() {
  const { me, signedOut, toast } = useShell();
  const [security, setSecurity] = useState<Security | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // profile
  const [name, setName] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<Me | null>(null);

  // the one code send serves both writes
  const [sending, setSending] = useState(false);
  const [codeSentTo, setCodeSentTo] = useState<string | null>(null);

  // password
  const [pw, setPw] = useState({ password: "", password2: "" });
  const [pwProof, setPwProof] = useState<Proof>({});
  const [pwBusy, setPwBusy] = useState(false);
  const [pwDone, setPwDone] = useState<string | null>(null);

  // email
  const [newEmail, setNewEmail] = useState("");
  const [emailProof, setEmailProof] = useState<Proof>({});
  const [emailBusy, setEmailBusy] = useState(false);
  const [emailNote, setEmailNote] = useState<string | null>(null);

  const load = useCallback(() => {
    getSecurity()
      .then((s) => {
        setSecurity(s);
        setLoadError(null);
      })
      .catch((err) => setLoadError(errorText(err, "Could not read your settings")));
  }, []);
  useEffect(() => {
    if (me) load();
  }, [me, load]);

  const who = saved ?? me;
  const displayName = name ?? who?.user.display_name ?? "";

  const saveName = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const next = await updateMe(displayName);
      setSaved(next);
      setName(null);
      toast("Name saved");
    } catch (err) {
      toast(errorText(err, "Could not save the name"), "err");
    } finally {
      setSaving(false);
    }
  };

  const sendCode = async () => {
    setSending(true);
    try {
      const res = await sendSecurityCode();
      setCodeSentTo(res.email);
      toast(`Code sent to ${res.email}`);
    } catch (err) {
      toast(errorText(err, "Could not send a code"), "err");
    } finally {
      setSending(false);
    }
  };

  const savePassword = async (e: FormEvent) => {
    e.preventDefault();
    if (!security) return;
    if (pw.password !== pw.password2) return toast("The two passwords don’t match", "err");
    if (pw.password.length < security.min_password_len)
      return toast(`A password needs at least ${security.min_password_len} characters`, "err");
    setPwBusy(true);
    try {
      const res = await setPassword(pw.password, pw.password2, pwProof);
      setSecurity({ ...security, ...res });
      setPw({ password: "", password2: "" });
      setPwProof({});
      setCodeSentTo(null);
      setPwDone(security.has_password ? "Password changed." : "Password set — you can log in with it now.");
      toast("Password saved");
    } catch (err) {
      toast(errorText(err, "Could not save the password"), "err");
    } finally {
      setPwBusy(false);
    }
  };

  const saveEmail = async (e: FormEvent) => {
    e.preventDefault();
    setEmailBusy(true);
    try {
      const res = await changeEmail(newEmail, emailProof);
      setEmailNote(`Confirmation sent for ${res.pending}: ${res.note}.`);
      setNewEmail("");
      setEmailProof({});
      setCodeSentTo(null);
      toast("Confirmation email sent");
    } catch (err) {
      toast(errorText(err, "Could not change the email"), "err");
    } finally {
      setEmailBusy(false);
    }
  };

  if (signedOut) {
    return (
      <div className="mx-auto w-full max-w-3xl p-6 text-[13px] text-white/60">Sign in to see your settings.</div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-4 sm:p-6">
      <header className="flex flex-wrap items-center gap-2">
        <SettingsIcon size={18} className="text-white/60" />
        <h1 className="text-[15px] tracking-wide">Settings</h1>
        <span className={HINT}>your name, your password, your workspaces</span>
      </header>

      {loadError ? (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-[13px] text-red-200">
          {loadError}{" "}
          <button type="button" className="underline" onClick={load}>
            try again
          </button>
        </div>
      ) : null}

      {/* ── profile ── */}
      <section className={CARD}>
        <SectionHead icon={UserRound} title="Profile" sub="what the studio calls you" />
        <form onSubmit={saveName} className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
          <div>
            <label className={LABEL} htmlFor="display-name">
              Name
            </label>
            <input
              id="display-name"
              className={FIELD}
              value={displayName}
              maxLength={80}
              placeholder={who?.user.email?.split("@")[0] ?? ""}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <button type="submit" className={PRI} disabled={saving || name === null}>
            {saving ? "Saving…" : "Save"}
          </button>
        </form>
        <p className={`${HINT} mt-2`}>
          Signed in as <span className="text-white/70">{who?.user.email ?? "—"}</span>
        </p>
      </section>

      {/* ── password ── */}
      <section className={CARD}>
        <SectionHead
          icon={KeyRound}
          title={security?.has_password ? "Change password" : "Set a password"}
          sub={
            security
              ? security.has_password
                ? "you log in with a password"
                : "you sign in with Google, Discord, Apple or an emailed code — add a password to log in with it too"
              : undefined
          }
        />
        {security && !security.can_change ? (
          <p className={HINT}>Sign-in isn’t configured on this server, so passwords can’t be changed here.</p>
        ) : security ? (
          <form onSubmit={savePassword} className="grid gap-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className={LABEL} htmlFor="new-password">
                  New password
                </label>
                <input
                  id="new-password"
                  className={FIELD}
                  type="password"
                  autoComplete="new-password"
                  minLength={security.min_password_len}
                  required
                  value={pw.password}
                  onChange={(e) => setPw({ ...pw, password: e.target.value })}
                />
              </div>
              <div>
                <label className={LABEL} htmlFor="new-password-2">
                  New password, again
                </label>
                <input
                  id="new-password-2"
                  className={FIELD}
                  type="password"
                  autoComplete="new-password"
                  minLength={security.min_password_len}
                  required
                  value={pw.password2}
                  onChange={(e) => setPw({ ...pw, password2: e.target.value })}
                />
              </div>
            </div>
            <ProofFields
              security={security}
              proof={pwProof}
              onChange={setPwProof}
              onSendCode={sendCode}
              sending={sending}
              codeSentTo={codeSentTo}
            />
            <div className="flex items-center gap-3">
              <button type="submit" className={PRI} disabled={pwBusy || !(pwProof.current_password || pwProof.code)}>
                {pwBusy ? "Saving…" : security.has_password ? "Change password" : "Set password"}
              </button>
              {pwDone ? <span className={HINT}>{pwDone}</span> : null}
            </div>
          </form>
        ) : !loadError ? (
          <p className={HINT}>Loading…</p>
        ) : null}
      </section>

      {/* ── email ── */}
      <section className={CARD}>
        <SectionHead icon={Mail} title="Email" sub="where codes and receipts go" />
        {security?.can_change ? (
          <form onSubmit={saveEmail} className="grid gap-3">
            <div>
              <label className={LABEL} htmlFor="new-email">
                New address
              </label>
              <input
                id="new-email"
                className={FIELD}
                type="email"
                autoComplete="email"
                required
                placeholder={security.email ?? ""}
                value={newEmail}
                onChange={(e) => setNewEmail(e.target.value)}
              />
            </div>
            <ProofFields
              security={security}
              proof={emailProof}
              onChange={setEmailProof}
              onSendCode={sendCode}
              sending={sending}
              codeSentTo={codeSentTo}
            />
            <div className="flex items-center gap-3">
              <button
                type="submit"
                className={PRI}
                disabled={emailBusy || !newEmail || !(emailProof.current_password || emailProof.code)}
              >
                {emailBusy ? "Sending…" : "Change email"}
              </button>
            </div>
            <p className={HINT}>
              {emailNote ??
                "You’ll get a confirmation email at the new address (and the old one). The change takes effect once it’s confirmed and you sign in again."}
            </p>
          </form>
        ) : (
          <p className={HINT}>{security?.email ?? "—"}</p>
        )}
      </section>

      {/* ── workspaces ── */}
      <section className={CARD}>
        <SectionHead icon={Users} title="Workspaces" sub="the accounts you belong to" />
        <ul className="grid gap-1">
          {(who?.accounts ?? []).map((a) => {
            const active = a.id === who?.account?.id;
            return (
              <li key={a.id} className="flex items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-white/[0.04]">
                <span
                  className="inline-block h-2.5 w-2.5 rounded-full"
                  style={{ background: a.accent || "rgb(255 255 255 / 0.3)" }}
                  aria-hidden
                />
                <span className="text-[13px] text-white/85">{a.label}</span>
                <span className={HINT}>
                  {a.role || "member"}
                  {active ? " · active" : ""}
                </span>
                {!active ? (
                  <button
                    type="button"
                    className={`${GHOST} ml-auto`}
                    onClick={() =>
                      switchAccount(a.slug)
                        .then(() => window.location.reload())
                        .catch(() => toast("Could not switch workspace", "err"))
                    }
                  >
                    Switch
                  </button>
                ) : null}
              </li>
            );
          })}
          {who && who.accounts.length === 0 ? <li className={HINT}>No workspace yet.</li> : null}
        </ul>
        <p className={`${HINT} mt-3`}>
          Members are added by invitation, never by signing up. Credits and plans live on the balance pill in the
          header.
        </p>
      </section>

      <div className="flex justify-end">
        <button type="button" className={GHOST} onClick={signOut}>
          Sign out of this device
        </button>
      </div>
    </div>
  );
}
