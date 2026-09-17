// The facts the public pages print. Fill these before the pilot opens to
// anyone but Mike -- the legal pages show a draft banner while any of them
// is still a placeholder.
export const SITE = {
  name: "ZeroPage",
  company: "Zero Page Films",
  legalEntity: "[legal entity or your name]",
  jurisdiction: "[state, country]",
  governingLaw: "[state]",
  contactEmail: "[contact email]",
  logRetentionDays: "[30]",
  effectiveDate: "on publication",
} as const;

export const isPlaceholder = (v: string) => v.startsWith("[");

export const LEGAL_IS_DRAFT = [
  SITE.legalEntity,
  SITE.jurisdiction,
  SITE.governingLaw,
  SITE.contactEmail,
  SITE.logRetentionDays,
].some(isPlaceholder);
