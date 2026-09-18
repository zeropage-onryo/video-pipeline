"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { signInThenCheckout, startCheckout } from "@/lib/site-billing";

type State =
  | { phase: "idle" }
  | { phase: "busy" }
  | { phase: "note"; message: string };

// One plan card's button. Click -> POST /api/billing/checkout -> Stripe.
// Not signed in -> sign in, come back to /pricing?checkout=<item>, and
// the button whose item matches picks the checkout up on load.
export function PlanButton({
  item,
  label,
  variant = "default",
}: {
  item: string;
  label: string;
  variant?: "default" | "outline";
}) {
  const [state, setState] = useState<State>({ phase: "idle" });
  const params = useSearchParams();
  const resume = params.get("checkout") === item;

  // The async half. Every state write happens after an await, in a
  // continuation -- never synchronously inside the effect below.
  function run(): Promise<void> {
    return startCheckout(item).then((outcome) => {
      if (outcome.kind === "redirect") {
        window.location.href = outcome.url;
        return;
      }
      if (outcome.kind === "sign-in") {
        signInThenCheckout(item);
        return;
      }
      setState({
        phase: "note",
        message:
          outcome.kind === "unconfigured"
            ? "Checkout isn't configured on this install yet."
            : outcome.message,
      });
    });
  }

  function go() {
    setState({ phase: "busy" });
    void run();
  }

  useEffect(() => {
    // back from sign-in with ?checkout=<this item>: pick the checkout up
    if (resume) void run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resume]);

  return (
    <div className="flex flex-col gap-2">
      <Button
        size="lg"
        variant={variant}
        className="w-full"
        disabled={state.phase === "busy"}
        onClick={go}
      >
        {state.phase === "busy" ? "Opening checkout…" : label}
        {state.phase !== "busy" && <ArrowRight data-icon="inline-end" className="size-4" />}
      </Button>
      {state.phase === "note" && (
        <p className="text-xs leading-relaxed text-[#82807d]" role="status">
          {state.message}
        </p>
      )}
    </div>
  );
}
