import { LinkCards } from "./link-cards";
import type { MakePage } from "../pages";

// "N video generator models": three renderers off the pricing catalog and
// a fourth card for the rest of the list, each with a Start now.
export function ModelsSection({ page }: { page: MakePage }) {
  return (
    <LinkCards
      id="models"
      title={page.models.title}
      items={page.models.items}
      spark={page.cta.spark}
      startLabel={page.cta.startLabel}
    />
  );
}
