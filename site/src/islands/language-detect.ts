// Story 4.7 (AC1): opportunistic browser-language redirect, present only on
// `/` (see index.astro -- this script is intentionally NOT wired into
// BriefingPage.astro, since every other route was an explicit language
// choice the reader already made and must never be redirected away from).
//
// AD-1 forbids computation at request time and this site is 100%
// static-generated (no SSR adapter, no server to read Accept-Language) --
// the only reachable signal for "what language does this reader prefer" is
// client-side navigator.language. Story 4.1's Cold-load guarantee (a no-JS
// reader sees the full French Briefing at `/` immediately, zero JS
// required) must not regress: this redirect is strictly additive/optional,
// runs only when JS actually executes, and never delays or replaces `/`'s
// existing unconditional French render -- a reader whose browser prefers
// French (or has JS disabled) sees no redirect and no flash at all.

type SupportedLanguage = "fr" | "en" | "es";

const SUPPORTED: readonly SupportedLanguage[] = ["fr", "en", "es"];

// A simple 2-letter-prefix match against the 3 supported codes is
// sufficient given only 3 languages exist today -- deliberately not a full
// BCP-47 subtag parse (e.g. distinguishing pt-BR from pt-PT would be
// overengineering for a site with no Portuguese content at all).
export function resolveLanguage(navigatorLanguage: string | undefined | null): SupportedLanguage {
  const prefix = navigatorLanguage?.slice(0, 2).toLowerCase();
  const match = SUPPORTED.find((lang) => lang === prefix);
  // FR-12: English is the fallback for an unsupported/unrecognized value,
  // not French -- French is this site's *default* Zone/Period, but a
  // reader whose browser signals a language this site can't identify
  // should not be assumed francophone just because `/` happens to be French.
  return match ?? "en";
}

export function shouldRedirect(resolvedLanguage: SupportedLanguage): boolean {
  return resolvedLanguage !== "fr";
}

export function redirectTargetFor(resolvedLanguage: SupportedLanguage): string {
  return `/${resolvedLanguage}/world/day`;
}

export function runRedirect(): void {
  const resolved = resolveLanguage(navigator.language);
  if (!shouldRedirect(resolved)) return;
  // window.location.replace, not .href -- so the French `/` page never
  // enters browser history as an intermediate state a reader could land
  // back on by pressing Back.
  window.location.replace(redirectTargetFor(resolved));
}

// Guarded so this module can be imported for unit-testing the pure
// functions above (resolveLanguage/shouldRedirect/redirectTargetFor)
// without a browser environment -- vitest's default environment has no
// `window`/`navigator`, and importing this file must not crash just to
// reach those exports.
if (typeof window !== "undefined") {
  runRedirect();
}
