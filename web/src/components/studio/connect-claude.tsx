"use client";

/* The "Connect to Claude" panel, opened from either account menu (the
   rail's profile row and the header's avatar). It connects nothing
   itself -- claude.ai does that, and our consent page is where the person
   says yes -- so it is the address to paste, the steps, and a way to the
   page on claude.ai where they happen. What it shows is lib/connect-claude's
   plan over /api/me, and -- once the person has pressed Allow, or Claude has
   used the connection -- the line GET /api/mcp/connection answers. */
import { useEffect, useRef, useState } from "react";
import { Check, CircleCheck, Copy, ExternalLink, X } from "lucide-react";
import {
  CLAUDE_CONNECTORS_URL,
  CONNECTOR_NAME,
  MANUAL_STEPS,
  connectPlan,
  connectedLine,
} from "@/lib/connect-claude";
import { getMcpConnection, type McpConnection, type Me } from "@/lib/studio-api";

export function ConnectClaude({
  me,
  onClose,
  toast,
}: {
  me: Me | null;
  onClose: () => void;
  toast: (text: string, kind?: "ok" | "err") => void;
}) {
  const plan = connectPlan(me);
  const field = useRef<HTMLInputElement>(null);
  const [copied, setCopied] = useState(false);
  const [status, setStatus] = useState<McpConnection | null>(null);
  const live = plan.mode !== "off";

  useEffect(() => {
    if (!live) return;
    let gone = false;
    getMcpConnection()
      .then((s) => !gone && setStatus(s))
      // unknown is not "not connected": the line just stays away
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [live]);
  const line = connectedLine(status);

  async function copy() {
    if (plan.mode === "off") return;
    try {
      await navigator.clipboard.writeText(plan.url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // no clipboard (an http origin, a refused permission): select the
      // address so the person's own copy takes it
      field.current?.select();
      toast("Press ⌘C to copy the address", "err");
    }
  }

  return (
    <div className="zmodal" onClick={onClose}>
      <div
        className="zdialog ccdialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cc-title"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.key === "Escape" && onClose()}
      >
        <div className="zdhead">
          <h3 id="cc-title">Connect to Claude</h3>
          <span className="spacer" />
          <button type="button" className="zdx" onClick={onClose} aria-label="Close" autoFocus>
            <X strokeWidth={1.8} />
          </button>
        </div>
        <div className="zdbody">
          <p className="cclede">
            Use your studio from Claude: read the board, write scenes, price and approve renders, with your yes
            before anything spends.
          </p>

          {plan.mode === "off" ? (
            <p className="ccnote">The Claude connector isn&apos;t switched on for this studio yet.</p>
          ) : (
            <>
              {line ? (
                <p className="ccstatus" role="status">
                  <CircleCheck strokeWidth={1.8} /> {line}
                </p>
              ) : null}
              <div className="zfield">
                <label className="m" htmlFor="cc-url">
                  Connector address
                </label>
                <div className="ccurl">
                  <input
                    id="cc-url"
                    ref={field}
                    className="zin"
                    value={plan.url}
                    readOnly
                    onFocus={(e) => e.currentTarget.select()}
                  />
                  <button type="button" className="zbtn" onClick={() => void copy()}>
                    {copied ? <Check strokeWidth={1.8} /> : <Copy strokeWidth={1.8} />}
                    {copied ? "Copied" : "Copy"}
                  </button>
                </div>
              </div>

              {plan.mode === "directory" ? (
                <a className="zbtn pri ccgo" href={plan.listing} target="_blank" rel="noopener noreferrer">
                  Add {CONNECTOR_NAME} in Claude <ExternalLink strokeWidth={1.8} />
                </a>
              ) : (
                <>
                  <ol className="ccsteps">
                    {MANUAL_STEPS.map((step) => (
                      <li key={step}>{step}</li>
                    ))}
                  </ol>
                  <a className="zbtn pri ccgo" href={CLAUDE_CONNECTORS_URL} target="_blank" rel="noopener noreferrer">
                    Open Claude connectors <ExternalLink strokeWidth={1.8} />
                  </a>
                </>
              )}

              <p className="ccnote">
                Already connected? To disconnect, remove {CONNECTOR_NAME} in claude.ai under{" "}
                <a href={CLAUDE_CONNECTORS_URL} target="_blank" rel="noopener noreferrer">
                  Customize → Connectors
                </a>
                .
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
