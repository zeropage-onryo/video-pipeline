import { LinkCards } from "./link-cards";
import type { MakePage } from "../pages";

// "How to make a product ad": three numbered cards, the product's own
// sequence (upload, look + approve, render), each with a Start now.
export function HowToSection({ page }: { page: MakePage }) {
  return (
    <LinkCards
      id="how"
      title={page.howTo.title}
      items={page.howTo.items}
      spark={page.cta.spark}
      startLabel={page.cta.startLabel}
      numbered
    />
  );
}
