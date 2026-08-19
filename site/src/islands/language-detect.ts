// Story 4.7 (AC1): opportunistic browser-language redirect, present only on
// `/` (see index.astro -- this script is intentionally NOT wired into
// BriefingPage.astro, since every other route was an explicit language
// choice the reader already made and must never be redirected away from).
//
// Extended since to consult the reader's stored preference FIRST: a
// returning reader resumes their own last Zone/Period/Language, and only
// a reader with no stored preference at all (a genuine first visit) gets
// the browser-language guess. navigator.language is a guess about where
// someone is; the stored preference is something they actually chose, so
// the guess must never override it.
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

import {
  browserStorage,
  LANGUAGE_CYCLE,
  readPreference,
  routePath,
  type LanguageSlug,
  type RoutePreference,
} from "./preferences";

type SupportedLanguage = LanguageSlug;

const SUPPORTED: readonly SupportedLanguage[] = LANGUAGE_CYCLE;

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

// What `/` already renders with zero JS (index.astro): French, World,
// today. A preference pointing here needs no redirect at all -- the
// reader is already looking at exactly that Briefing.
export const DEFAULT_ENTRY_PATH = "/fr/world/day";

/**
 * Where `/` should send this reader, or null to leave them on the French
 * World/day page `/` already rendered.
 *
 * Stored preference wins outright when present; the browser-language
 * guess is consulted only in its absence. Pure, so both branches are
 * unit-testable without a browser.
 */
export function entryTargetFor(
  stored: RoutePreference | null,
  navigatorLanguage: string | undefined | null
): string | null {
  if (stored) {
    const path = routePath(stored);
    return path === DEFAULT_ENTRY_PATH ? null : path;
  }

  const resolved = resolveLanguage(navigatorLanguage);
  return shouldRedirect(resolved) ? redirectTargetFor(resolved) : null;
}

export function runRedirect(): void {
  const target = entryTargetFor(readPreference(browserStorage()), navigator.language);
  if (!target) return;
  // window.location.replace, not .href -- so the French `/` page never
  // enters browser history as an intermediate state a reader could land
  // back on by pressing Back.
  window.location.replace(target);
}

// Guarded so this module can be imported for unit-testing the pure
// functions above (resolveLanguage/shouldRedirect/redirectTargetFor)
// without a browser environment -- vitest's default environment has no
// `window`/`navigator`, and importing this file must not crash just to
// reach those exports.
if (typeof window !== "undefined") {
  runRedirect();
}
