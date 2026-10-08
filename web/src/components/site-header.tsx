"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ChevronDown, Menu as MenuIcon, X } from "lucide-react";
import { NavigationMenu as Menu } from "@base-ui/react/navigation-menu";
import { Dialog } from "@base-ui/react/dialog";
import { Accordion as AccordionPrimitive } from "@base-ui/react/accordion";
import { Accordion, AccordionItem } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { goToSignIn } from "@/lib/api";
import { Wordmark } from "@/components/wordmark";
import { skinClass, useTone } from "@/components/editorial-skin";
import { makePath, pagesIn } from "@/landing-pages/pages";
import { MODELS } from "@/lib/catalog";
import { pageLabel } from "@/landing-pages/shared";

// Fixed 60px bar: transparent while the page is at the top, glass (blur +
// hairline) once scrolled. The state is written to a data attribute the
// CSS reads (`.glass-nav[data-at-top]`) rather than React state, so the
// scroll listener never re-renders the tree.
//
// "Solutions" (Mike, 2026-10-02) sits right of "How it works" and opens a
// panel listing every /make landing page by its short `menu` line, off the
// same list the footer and the sitemap read -- adding a page adds the row.
// The image-model pages live under /models and are listed there, not here
// (2026-10-05, Mike's call).
const BEFORE = [{ href: "/#how", label: "How it works" }];
const AFTER = [
  { href: "/pricing", label: "Pricing" },
  { href: "/faq", label: "FAQ" },
];

// "Models" (Mike, 2026-10-05) is a second panel: every model's own page under
// /models/<slug>, video in one column and image in the other, with the
// overview at the top. A page is video when its first model id is in the
// pricing catalog; the rest are the composer's image models.
const isVideoPage = (p: { modelIds?: string[] }) => MODELS.some((m) => m.model === p.modelIds?.[0]);

const ITEM =
  "inline-flex h-9 items-center rounded-md px-3 text-[13.5px] tracking-[-0.005em] text-[var(--nav-fg)] transition-colors outline-none hover:bg-secondary hover:text-foreground focus-visible:bg-secondary focus-visible:text-foreground";

export function SiteHeader() {
  const bar = useRef<HTMLElement>(null);
  // The Solutions panel portals to <body>, outside the skin wrapper, so it
  // carries the page's tone itself or it draws dark on a white page.
  const tone = useTone();

  useEffect(() => {
    const el = bar.current;
    if (!el) return;
    const update = () => {
      el.dataset.atTop = window.scrollY < 8 ? "true" : "false";
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    return () => window.removeEventListener("scroll", update);
  }, []);

  return (
    <header
      ref={bar}
      data-at-top="true"
      className="glass-nav fixed inset-x-0 top-0 z-50 border-b border-transparent"
    >
      <div className="mx-auto flex h-[60px] max-w-[1440px] items-center justify-between gap-10 px-6">
        <Wordmark intro />

        <Menu.Root className="hidden md:block" aria-label="Site">
          <Menu.List className="flex items-center gap-1">
            {BEFORE.map((link) => (
              <Menu.Item key={link.href}>
                <Menu.Link render={<Link href={link.href} />} className={ITEM}>
                  {link.label}
                </Menu.Link>
              </Menu.Item>
            ))}

            <Menu.Item>
              <Menu.Trigger className={`${ITEM} group/solutions gap-1 data-popup-open:bg-secondary data-popup-open:text-foreground`}>
                Solutions
                <ChevronDown
                  aria-hidden
                  strokeWidth={1.75}
                  className="size-3.5 transition-transform duration-200 group-data-popup-open/solutions:rotate-180"
                />
              </Menu.Trigger>
              <Menu.Content className="w-[300px] p-1.5 data-ending-style:opacity-0 data-starting-style:opacity-0 transition-opacity duration-200">
                <ul className="flex flex-col">
                  {pagesIn("make").map((page) => (
                    <li key={page.slug}>
                      <Menu.Link
                        render={<Link href={makePath(page.slug)} />}
                        closeOnClick
                        className="block rounded-md px-3 py-2.5 transition-colors outline-none hover:bg-secondary focus-visible:bg-secondary"
                      >
                        <span className="block text-[14px] font-medium tracking-[-0.005em] text-foreground">
                          {page.menu}
                        </span>
                        <span className="mt-0.5 block text-[12.5px] leading-snug text-[var(--ink-3)]">
                          {page.subhead}
                        </span>
                      </Menu.Link>
                    </li>
                  ))}
                </ul>
              </Menu.Content>
            </Menu.Item>

            <Menu.Item>
              <Menu.Trigger className={`${ITEM} group/models gap-1 data-popup-open:bg-secondary data-popup-open:text-foreground`}>
                Models
                <ChevronDown
                  aria-hidden
                  strokeWidth={1.75}
                  className="size-3.5 transition-transform duration-200 group-data-popup-open/models:rotate-180"
                />
              </Menu.Trigger>
              <Menu.Content className="w-[520px] p-1.5 data-ending-style:opacity-0 data-starting-style:opacity-0 transition-opacity duration-200">
                <Menu.Link
                  render={<Link href="/models" />}
                  closeOnClick
                  className="block rounded-md px-3 py-2.5 transition-colors outline-none hover:bg-secondary focus-visible:bg-secondary"
                >
                  <span className="block text-[14px] font-medium tracking-[-0.005em] text-foreground">All models</span>
                  <span className="mt-0.5 block text-[12.5px] leading-snug text-[var(--ink-3)]">
                    Every renderer, the tier that unlocks it, and what a clip costs.
                  </span>
                </Menu.Link>
                <div className="mt-1 grid grid-cols-2 gap-1 border-t border-border pt-2">
                  {(
                    [
                      ["Video", pagesIn("models").filter(isVideoPage)],
                      ["Image", pagesIn("models").filter((p) => !isVideoPage(p))],
                    ] as const
                  ).map(([group, pages]) => (
                    <div key={group}>
                      <span className="eyebrow block px-3 pt-1.5 pb-1">{group}</span>
                      <ul className="flex flex-col">
                        {pages.map((page) => (
                          <li key={page.slug}>
                            <Menu.Link
                              render={<Link href={makePath(page)} />}
                              closeOnClick
                              className="block rounded-md px-3 py-2 text-[14px] font-medium tracking-[-0.005em] text-foreground transition-colors outline-none hover:bg-secondary focus-visible:bg-secondary"
                            >
                              {pageLabel(page)}
                            </Menu.Link>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              </Menu.Content>
            </Menu.Item>

            {AFTER.map((link) => (
              <Menu.Item key={link.href}>
                <Menu.Link render={<Link href={link.href} />} className={ITEM}>
                  {link.label}
                </Menu.Link>
              </Menu.Item>
            ))}
          </Menu.List>

          <Menu.Portal>
            <Menu.Positioner
              side="bottom"
              sideOffset={6}
              align="start"
              className={`${skinClass(tone)} z-[60] h-(--positioner-height) w-(--positioner-width) max-w-(--available-width) text-foreground transition-[top,left] duration-200 data-instant:transition-none`}
            >
              <Menu.Popup className="h-(--popup-height) w-(--popup-width) origin-(--transform-origin) rounded-xl border border-border bg-popover text-popover-foreground shadow-[0_12px_40px_-12px_rgba(0,0,0,0.25)] transition-[opacity,transform,width,height] duration-200 outline-none data-ending-style:scale-95 data-ending-style:opacity-0 data-starting-style:scale-95 data-starting-style:opacity-0">
                <Menu.Viewport className="relative size-full overflow-hidden" />
              </Menu.Popup>
            </Menu.Positioner>
          </Menu.Portal>
        </Menu.Root>

        <div className="flex items-center gap-2">
          {/* Straight to the one sign-in door, the way InVideo and LTX
              Studio do it: both buttons open the same page, and the first
              pass through it creates the workspace. "Sign up" only
              asks for the sign-up heading. A visitor who is already signed
              in is handed on to /studio by the door itself. Under 640px
              "Log in" moves into the menu so the bar fits a 320px phone. */}
          <Button variant="ghost" size="sm" className="hidden text-foreground sm:inline-flex" onClick={() => goToSignIn()}>
            Log in
          </Button>
          <Button size="sm" onClick={() => goToSignIn("signup")}>
            Sign up
          </Button>
          <MobileMenu />
        </div>
      </div>
    </header>
  );
}

// Below md the nav above is hidden, and until 2026-10-08 nothing took its
// place: on a phone the only way to another page was the footer (found on
// the live GPT Image 2.5 page). This is the same five entries as one sheet,
// Solutions and Models folding open, with both sign-in doors at the foot,
// read off the same lists as the bar so the two menus cannot drift. It
// renders inside the page's skin wrapper rather than at <body> (the bar's
// panels portal to <body> and carry the tone themselves), so it also gets
// the page's accent: on a model page its Sign up is that page's colour, the
// same as the bar's. The wrapper has no transform or filter, so the fixed
// sheet still covers the screen.
const ROW =
  "flex min-h-12 w-full items-center justify-between rounded-lg px-3 text-left text-[17px] font-medium tracking-[-0.01em] text-foreground outline-none transition-colors hover:bg-secondary focus-visible:bg-secondary";
const SUB =
  "block rounded-lg px-3 py-2.5 text-[15px] font-medium tracking-[-0.005em] text-foreground outline-none transition-colors hover:bg-secondary focus-visible:bg-secondary";

function MobileMenu() {
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const home = useRef<HTMLElement | null>(null);
  const onOpenChange = (next: boolean) => {
    if (next) home.current = trigger.current?.closest<HTMLElement>(".editorial") ?? document.body;
    setOpen(next);
  };

  // a sheet left open while the window widens past md would sit hidden
  // over a locked page
  useEffect(() => {
    const wide = window.matchMedia("(min-width: 768px)");
    const onChange = () => wide.matches && setOpen(false);
    wide.addEventListener("change", onChange);
    return () => wide.removeEventListener("change", onChange);
  }, []);

  const folds = [
    {
      value: "solutions",
      label: "Solutions",
      body: (
        <ul className="flex flex-col pb-2">
          {pagesIn("make").map((page) => (
            <li key={page.slug}>
              <Link href={makePath(page.slug)} onClick={close} className={SUB}>
                {page.menu}
                <span className="mt-0.5 block text-[13px] font-normal leading-snug text-[var(--ink-3)]">{page.subhead}</span>
              </Link>
            </li>
          ))}
        </ul>
      ),
    },
    {
      value: "models",
      label: "Models",
      body: (
        <div className="pb-2">
          <Link href="/models" onClick={close} className={SUB}>
            All models
          </Link>
          <div className="mt-1 grid grid-cols-2 gap-1">
            {(
              [
                ["Video", pagesIn("models").filter(isVideoPage)],
                ["Image", pagesIn("models").filter((p) => !isVideoPage(p))],
              ] as const
            ).map(([group, pages]) => (
              <div key={group}>
                <span className="eyebrow block px-3 pt-1.5 pb-1">{group}</span>
                <ul className="flex flex-col">
                  {pages.map((page) => (
                    <li key={page.slug}>
                      <Link href={makePath(page)} onClick={close} className={SUB}>
                        {pageLabel(page)}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      ),
    },
  ];

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Trigger
        ref={trigger}
        aria-label="Open menu"
        className="inline-flex size-9 items-center justify-center rounded-md text-foreground outline-none transition-colors hover:bg-secondary focus-visible:ring-3 focus-visible:ring-ring/50 md:hidden"
      >
        <MenuIcon aria-hidden className="size-5" strokeWidth={1.75} />
      </Dialog.Trigger>
      <Dialog.Portal container={home}>
        <Dialog.Popup
          className={`fixed inset-0 z-[70] flex flex-col bg-background text-foreground outline-none transition-[opacity,transform] duration-200 data-ending-style:-translate-y-2 data-ending-style:opacity-0 data-starting-style:-translate-y-2 data-starting-style:opacity-0 motion-reduce:transition-none md:hidden`}
        >
          <Dialog.Title className="sr-only">Menu</Dialog.Title>
          <div className="flex h-[60px] shrink-0 items-center justify-between border-b border-border px-6">
            {/* the wordmark is a link home: following it closes the sheet */}
            <span onClick={close}>
              <Wordmark />
            </span>
            <Dialog.Close
              aria-label="Close menu"
              className="inline-flex size-9 items-center justify-center rounded-md text-foreground outline-none transition-colors hover:bg-secondary focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <X aria-hidden className="size-5" strokeWidth={1.75} />
            </Dialog.Close>
          </div>

          <nav aria-label="Site" className="flex-1 overflow-y-auto overscroll-contain px-3 py-3">
            {BEFORE.map((link) => (
              <Link key={link.href} href={link.href} onClick={close} className={ROW}>
                {link.label}
              </Link>
            ))}
            <Accordion>
              {folds.map((fold) => (
                <AccordionItem key={fold.value} value={fold.value} className="border-none">
                  <AccordionPrimitive.Header className="flex">
                    <AccordionPrimitive.Trigger className={`${ROW} group/fold`}>
                      {fold.label}
                      <ChevronDown
                        aria-hidden
                        strokeWidth={1.75}
                        className="size-4 text-[var(--ink-3)] transition-transform duration-200 group-aria-expanded/fold:rotate-180"
                      />
                    </AccordionPrimitive.Trigger>
                  </AccordionPrimitive.Header>
                  <AccordionPrimitive.Panel className="h-(--accordion-panel-height) overflow-hidden pl-3 transition-[height] duration-200 ease-out data-ending-style:h-0 data-starting-style:h-0 motion-reduce:transition-none">
                    {fold.body}
                  </AccordionPrimitive.Panel>
                </AccordionItem>
              ))}
            </Accordion>
            {AFTER.map((link) => (
              <Link key={link.href} href={link.href} onClick={close} className={ROW}>
                {link.label}
              </Link>
            ))}
          </nav>

          <div className="grid shrink-0 grid-cols-2 gap-2 border-t border-border px-6 pt-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
            <Button
              variant="outline"
              size="lg"
              onClick={() => {
                close();
                goToSignIn();
              }}
            >
              Log in
            </Button>
            <Button
              size="lg"
              onClick={() => {
                close();
                goToSignIn("signup");
              }}
            >
              Sign up
            </Button>
          </div>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
