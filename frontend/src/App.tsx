// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useEffect, useRef, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Link, Navigate, Outlet, useNavigate, useOutletContext } from "react-router-dom";
import {
  Archive,
  BarChart3,
  Check,
  Monitor,
  Moon,
  Settings,
  Sun,
  Unplug,
  type LucideIcon,
} from "lucide-react";
import { api, loginUrl, logoutUrl, silentLoginUrl, type SitePublic, type Whoami } from "./api";
import { localizedText, setDefaultContentLang, setTranslationEnabled } from "@basicbar/ui";
import Footer from "./components/Footer";
import JoinByCode from "./components/JoinByCode";
import { LanguageMenu } from "./components/LanguageSwitcher";
import RichText from "./components/RichText";
import { EmptyState } from "./components/ui";
import RoomsPage from "./pages/RoomsPage";
import {
  useTheme,
  type Appearance,
} from "@basicbar/ui";

// --- Silent SSO + deep-link restore (#19, adopted from Ausleihbar) ----------
// Where to send the user once signed in; survives the full-page OIDC round-trip
// via sessionStorage (per-tab), consumed on the first authenticated load so a
// shared deep link like /sets/5/present still lands there after sign-in.
const REDIRECT_KEY = "postLoginRedirect";

/** Remember an in-app destination to return to after sign-in. The landing page
 *  ("/" and its ?sso markers) is never a destination. */
function rememberRedirect(path: string): void {
  if (path && path !== "/" && !path.startsWith("/?")) {
    sessionStorage.setItem(REDIRECT_KEY, path);
  }
}

function takeRedirect(): string | null {
  const target = sessionStorage.getItem(REDIRECT_KEY);
  if (target) sessionStorage.removeItem(REDIRECT_KEY);
  return target;
}

const currentPath = () => window.location.pathname + window.location.search;

/** Try the silent SSO login at most once per tab, and never right after a
 *  silent attempt or a logout (both marked via the ?sso= param). */
function shouldTrySilentLogin(): boolean {
  if (new URLSearchParams(window.location.search).has("sso")) return false;
  return !sessionStorage.getItem("ssoTried");
}

/** Full-page logout that also ends the Keycloak session; the ssoTried flag
 *  stops silent SSO from logging the user straight back in (#19). */
function doLogout(): void {
  sessionStorage.setItem("ssoTried", "1");
  window.location.assign(logoutUrl);
}

/** Auto / Light / Dark rows, Ausleihbar's account-menu vocabulary:
 *  icon + label (+ hint) + check on the active option. */
function AppearanceControl({
  theme,
  onChange,
}: {
  theme: Appearance;
  onChange: (setting: Appearance) => void;
}) {
  const { t } = useTranslation();
  const options: {
    value: Appearance;
    label: string;
    hint?: string;
    icon: LucideIcon;
  }[] = [
    { value: "auto", label: t("Auto"), hint: t("(follows your system)"), icon: Monitor },
    { value: "light", label: t("Light"), icon: Sun },
    { value: "dark", label: t("Dark"), icon: Moon },
  ];
  return (
    <div role="radiogroup" aria-label={t("Appearance")}>
      <p className="px-3 pb-0.5 pt-1 text-xs text-slate-400 dark:text-slate-500">
        {t("Appearance")}
      </p>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={theme === option.value}
          onClick={() => onChange(option.value)}
          className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          <option.icon aria-hidden className="h-4 w-4 text-slate-400" />
          <span className="flex-1">
            {option.label}
            {option.hint && (
              <span className="block text-xs text-slate-400 dark:text-slate-500">
                {option.hint}
              </span>
            )}
          </span>
          {theme === option.value && (
            <Check aria-hidden className="h-4 w-4 text-brand-600" />
          )}
        </button>
      ))}
    </div>
  );
}

function UserMenu({ whoami }: { whoami: Whoami }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const { appearance, setAppearance } = useTheme();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const name = whoami.first_name || whoami.username || "?";
  const displayName =
    [whoami.first_name, whoami.last_name].filter(Boolean).join(" ") ||
    whoami.username;

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t("User menu")}
        className="flex items-center rounded-full p-1 transition-colors duration-150 hover:bg-slate-100 dark:hover:bg-slate-800"
      >
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-400 text-sm font-bold text-slate-900">
          {name[0].toUpperCase()}
        </span>
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-30 mt-2 w-56 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-lg shadow-slate-900/5 dark:border-slate-700 dark:bg-slate-900"
        >
          <p className="truncate px-3 py-2 text-xs text-slate-400 dark:text-slate-500">
            {t("Signed in as")}{" "}
            <span className="font-medium text-slate-600 dark:text-slate-300">
              {displayName}
            </span>
          </p>
          <div className="my-1 border-t border-slate-100 dark:border-slate-800" />
          <AppearanceControl theme={appearance} onChange={setAppearance} />
          <div className="my-1 border-t border-slate-100 dark:border-slate-800" />
          <Link
            to="/archiv"
            role="menuitem"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2 px-3 py-2.5 text-sm text-slate-700 hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            <Archive aria-hidden className="h-4 w-4 text-slate-400" />
            {t("Archived rooms")}
          </Link>
          {whoami.is_staff && (
            <Link
              to="/admin"
              role="menuitem"
              onClick={() => setOpen(false)}
              className="block px-3 py-2.5 text-sm text-slate-700 hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              {t("Manage website")}
            </Link>
          )}
          <div className="my-1 border-t border-slate-100 dark:border-slate-800" />
          <button
            type="button"
            onClick={doLogout}
            role="menuitem"
            className="block w-full px-3 py-2.5 text-left text-sm text-slate-700 hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            {t("Sign out")}
          </button>
        </div>
      )}
    </div>
  );
}

export interface AppContext {
  whoami: Whoami | null;
  site: SitePublic | null;
  setEasyMode: (easyMode: boolean) => void;
}

export function useApp() {
  return useOutletContext<AppContext>();
}

/** Easy mode (#52): a UI preference that simplifies the UI. The backend
 * reports the effective mode per role default (non-staff start in "simple",
 * staff start in "pro"), but any signed-in user may toggle between them. */
export function useEasyMode(): boolean {
  return useApp().whoami?.easy_mode ?? false;
}

/** Layout shell: header (logo/login), routed content, global footer. */
export default function App() {
  const { t } = useTranslation();
  const [whoami, setWhoami] = useState<Whoami | null>(null);
  const [site, setSite] = useState<SitePublic | null>(null);
  const [error, setError] = useState(false);
  const navigate = useNavigate();

  const setEasyMode = (easyMode: boolean) => {
    void api
      .setMode(easyMode)
      .then((res) => {
        setWhoami((prev) => (prev ? { ...prev, easy_mode: res.easy_mode } : prev));
      })
      .catch(() => {});
  };

  useEffect(() => {
    api.getSite().then(setSite).catch(() => setSite(null));
    api
      .whoami()
      .then((data) => {
        // Silent SSO (#19): a visitor who already has a Keycloak session is
        // logged in automatically via a one-shot prompt=none redirect; if the
        // IdP has no session the backend bounces to "/?sso=failed" and we show
        // the landing. Guards (once-per-tab flag + ?sso marker, also set on
        // logout) prevent redirect loops and re-login right after logging out.
        if (!data.authenticated && shouldTrySilentLogin()) {
          sessionStorage.setItem("ssoTried", "1");
          rememberRedirect(currentPath());
          window.location.assign(silentLoginUrl);
          return; // navigating away — keep whoami null (loading)
        }
        setWhoami(data);
        // Content-i18n (#33 MR2): the canonical authoring language and
        // whether machine-translation pre-fill is on, for `localizedText`.
        setDefaultContentLang(data.content_default_language);
        setTranslationEnabled(data.content_translation_enabled);
        // Back from sign-in with a remembered deep link → go there, not "/".
        if (data.authenticated) {
          const target = takeRedirect();
          if (target && target !== currentPath()) navigate(target, { replace: true });
        }
      })
      .catch(() => setError(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex min-h-screen flex-col overflow-x-hidden bg-white font-sans text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <header className="border-b border-slate-200 dark:border-slate-800">
        <div className="mx-auto flex w-full max-w-5xl items-center justify-between px-4 py-3">
          <Link to="/" className="flex items-center gap-3">
            {site?.logo && (
              <>
                <img
                  src={site.logo}
                  alt={t("Institution logo")}
                  className="h-8 w-auto max-w-[160px] object-contain"
                />
                <span
                  aria-hidden
                  className="h-7 w-px bg-slate-200 dark:bg-slate-700"
                />
              </>
            )}
            <span
              className={`text-xl font-extrabold tracking-tight${site?.logo ? " hidden sm:inline" : ""}`}
            >
              abstimm<span className="text-brand-700 dark:text-brand-300">BAR</span>
            </span>
          </Link>
          {whoami?.authenticated ? (
            <div className="flex items-center gap-1">
              {whoami.is_staff && (
                <Link
                  to="/admin"
                  aria-label={t("Manage website")}
                  title={t("Manage website")}
                  className="rounded-full p-2 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                >
                  <Settings aria-hidden className="h-5 w-5" />
                </Link>
              )}
              <div
                className="flex items-center rounded-full border border-slate-200 p-0.5 text-xs dark:border-slate-700"
                role="group"
                aria-label={t("Mode")}
              >
                <button
                  type="button"
                  aria-pressed={whoami.easy_mode === true}
                  onClick={() => setEasyMode(true)}
                  className={`min-w-[4rem] rounded-full px-2.5 py-1 text-center ${whoami.easy_mode ? "bg-brand-100 text-brand-800 dark:bg-brand-900 dark:text-brand-200" : "text-slate-500 dark:text-slate-400"}`}
                >
                  {t("Simple")}
                </button>
                <button
                  type="button"
                  aria-pressed={whoami.easy_mode === false}
                  onClick={() => setEasyMode(false)}
                  className={`min-w-[4rem] rounded-full px-2.5 py-1 text-center ${!whoami.easy_mode ? "bg-brand-100 text-brand-800 dark:bg-brand-900 dark:text-brand-200" : "text-slate-500 dark:text-slate-400"}`}
                >
                  {t("Pro")}
                </button>
              </div>
              <LanguageMenu authenticated />
              <UserMenu whoami={whoami} />
            </div>
          ) : (
            <div className="flex items-center gap-1">
              <LanguageMenu />
              <a
                href={loginUrl}
                onClick={() => rememberRedirect(currentPath())}
                className="rounded-lg bg-brand-400 px-3 py-1.5 text-sm font-semibold text-slate-900 hover:bg-brand-500"
              >
                {t("Sign in")}
              </a>
            </div>
          )}
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">
        {error ? (
          <EmptyState icon={Unplug} title={t("Backend unreachable")}>
            <Trans
              i18nKey="Is <code>docker compose up</code> running?"
              components={{ code: <code /> }}
            />
          </EmptyState>
        ) : (
          <Outlet context={{ whoami, site, setEasyMode }} />
        )}
      </main>

      <Footer />
    </div>
  );
}

/** Index route: rooms for signed-in staff, the landing page otherwise. */
export function Home() {
  const { t } = useTranslation();
  const { whoami, site } = useApp();
  if (!whoami) return null;
  if (whoami.authenticated) return <RoomsPage />;
  const landingText = localizedText(site?.landing_text);
  return (
    <div className="mx-auto max-w-2xl">
      <div className="mb-6">
        <JoinByCode />
      </div>
      {landingText ? (
        <RichText html={landingText} />
      ) : (
        <EmptyState icon={BarChart3} title={t("Live quizzes and polls for teaching")}>
          <p>
            {t(
              "Sign in to create rooms and question sets. Participating is always possible later without signing in.",
            )}
          </p>
        </EmptyState>
      )}
      <div className="mt-6">
        <a
          href={loginUrl}
          onClick={() => rememberRedirect(currentPath())}
          className="inline-block rounded-lg bg-brand-400 px-4 py-2 text-sm font-semibold text-slate-900 hover:bg-brand-500"
        >
          {t("Sign in")}
        </a>
      </div>
    </div>
  );
}

/** Gate for the authoring pages: redirect anonymous visitors to the landing. */
export function RequireAuth() {
  const ctx = useApp();
  if (!ctx.whoami) return null; // still loading
  if (!ctx.whoami.authenticated) return <Navigate to="/" replace />;
  return <Outlet context={ctx} />;
}
