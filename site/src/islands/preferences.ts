// The reader's last Zone / Period / Output Language, kept on their own
// device so re-opening the app resumes where they left off instead of
// snapping back to the browser-language default (a reader in Spain who
// reads in French had to re-pick French on every single open).
//
// AD-1 forbids computation at request time and this site is 100%
// static-generated -- there is no server, no session, and no account that
// could hold this. localStorage on the reader's own device is the only
// place the preference can live, and nothing here is ever sent anywhere.
//
// This module owns the browser-side answer to "is this a real, routable
// Briefing address". The three slug cycles below are hand-kept mirrors of
// src/lib/briefing.ts's own OUTPUT_LANGUAGE_CYCLE / ZONE_CYCLE / periods
// (never imported -- that lib is Astro/Node-side and not bundled for the
// browser; see period-switcher.ts's module docstring), but they live here
// rather than in period-switcher.ts so both browser islands share one
// copy instead of two: period-switcher.ts imports them from here, and
// language-detect.ts validates against them too.
//
// Validating on READ matters as much as on write. A Zone that a later
// config change drops -- as the 15 -> 4 Zone narrowing on 2026-08-19
// already did once -- would otherwise strand a returning reader on a 404
// forever, since the stale stored value would keep redirecting them there
// on every open, with no way back short of clearing site data.

export const PERIOD_CYCLE = ["day", "week"] as const;
export type PeriodSlug = (typeof PERIOD_CYCLE)[number];

export const LANGUAGE_CYCLE = ["fr", "en", "es"] as const;
export type LanguageSlug = (typeof LANGUAGE_CYCLE)[number];

export const ZONE_CYCLE = ["world", "europe", "france", "spain"] as const;
export type ZoneSlug = (typeof ZONE_CYCLE)[number];

export interface RoutePreference {
  lang: LanguageSlug;
  zone: ZoneSlug;
  period: PeriodSlug;
}

// Versioned so a future shape change can be introduced by bumping the key
// rather than by writing migration code for a value that is, at worst,
// cheap to lose (the reader re-picks once).
export const PREFERENCE_STORAGE_KEY = "5news.route-preference.v1";

export function isLanguageSlug(value: unknown): value is LanguageSlug {
  return LANGUAGE_CYCLE.includes(value as LanguageSlug);
}

export function isZoneSlug(value: unknown): value is ZoneSlug {
  return ZONE_CYCLE.includes(value as ZoneSlug);
}

export function isPeriodSlug(value: unknown): value is PeriodSlug {
  return PERIOD_CYCLE.includes(value as PeriodSlug);
}

/** The canonical page path for a preference -- mirrors period-switcher.ts's pageUrl. */
export function routePath(preference: RoutePreference): string {
  return `/${preference.lang}/${preference.zone}/${preference.period}`;
}

/**
 * Reads a route triple back out of a pathname, or null when the path is
 * not one of the 24 published Briefing addresses.
 *
 * `/` deliberately returns null, not the fr/world/day it happens to
 * render: `/` is the neutral entry point, never an explicit choice the
 * reader made, and recording it as one would overwrite a real preference
 * on the very load that is about to act on it.
 *
 * A trailing `.html` is tolerated because the build emits one file per
 * route (astro.config.mjs's `format: "file"`); Vercel's `cleanUrls` hides
 * the extension in production, but a direct hit on the file, or a local
 * `astro preview`, can still surface it.
 */
export function routeFromPathname(pathname: string): RoutePreference | null {
  const segments = pathname.replace(/\.html$/, "").split("/").filter(Boolean);
  if (segments.length !== 3) return null;

  const [lang, zone, period] = segments;
  if (!isLanguageSlug(lang) || !isZoneSlug(zone) || !isPeriodSlug(period)) return null;
  return { lang, zone, period };
}

/**
 * Parses a stored preference, returning null for anything that isn't a
 * complete, still-routable triple -- malformed JSON, a partial object, or
 * a slug this build no longer publishes.
 */
export function parsePreference(raw: string | null | undefined): RoutePreference | null {
  if (!raw) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object") return null;

  const { lang, zone, period } = parsed as Record<string, unknown>;
  if (!isLanguageSlug(lang) || !isZoneSlug(zone) || !isPeriodSlug(period)) return null;
  return { lang, zone, period };
}

export function serializePreference(preference: RoutePreference): string {
  return JSON.stringify({
    lang: preference.lang,
    zone: preference.zone,
    period: preference.period,
  });
}

// The narrow slice of the Storage interface this module needs -- lets the
// read/write helpers be unit-tested against a plain object, without jsdom
// (not a dependency of this project; see period-switcher.test.ts's own
// note on why).
export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

/**
 * The real localStorage, or null when it is unreachable. Merely *touching*
 * `localStorage` throws in a sandboxed iframe or with site data blocked,
 * so the access itself is guarded, not just the calls on it.
 */
export function browserStorage(): StorageLike | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export function readPreference(storage: StorageLike | null): RoutePreference | null {
  if (!storage) return null;
  try {
    return parsePreference(storage.getItem(PREFERENCE_STORAGE_KEY));
  } catch {
    return null;
  }
}

/**
 * Persists a preference, swallowing every failure. Storing is a
 * convenience, never a precondition for reading the Briefing: Safari's
 * private mode and a full quota both throw on setItem, and neither may
 * surface to the reader or interrupt the swap that triggered it.
 */
export function writePreference(storage: StorageLike | null, preference: RoutePreference): void {
  if (!storage) return;
  try {
    storage.setItem(PREFERENCE_STORAGE_KEY, serializePreference(preference));
  } catch {
    // Intentionally empty -- see this function's docstring.
  }
}

/**
 * Records the address currently in the URL bar as the reader's preference.
 *
 * Called on every Briefing page load, so a preference is captured whether
 * the reader got there by the client-side swap or by a real navigation
 * (the no-JS path, and period-switcher.ts's own degrade-to-navigation
 * fallback, both land here). `/` records nothing -- see routeFromPathname.
 */
export function rememberCurrentRoute(pathname: string): void {
  const route = routeFromPathname(pathname);
  if (!route) return;
  writePreference(browserStorage(), route);
}
