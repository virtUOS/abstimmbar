// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Error page for the router (unknown address or a render error), replacing
 * React Router's developer fallback ("Unexpected Application Error … Hey
 * developer 👋"), which users saw e.g. for a self-check link (#279).
 *
 * Paths below are rendered by Django, not by this app. If one of them reaches
 * the SPA, the web server in front (reverse proxy) does not forward it — or
 * still runs an older configuration — so the page says so for the admins. */
import { isRouteErrorResponse, useLocation, useRouteError } from "react-router";
import { useTranslation } from "react-i18next";
import { FileQuestion, TriangleAlert } from "lucide-react";
import { EmptyState } from "../components/ui";

const SERVER_PATHS = ["/api/", "/admin/", "/oidc/", "/lti/", "/p/", "/r/", "/c/", "/question-preview/", "/media/", "/static/"];

export function isServerPath(pathname: string): boolean {
  return SERVER_PATHS.some((prefix) => pathname.startsWith(prefix));
}

export default function RouteError() {
  const { t } = useTranslation();
  const error = useRouteError();
  const { pathname } = useLocation();
  const notFound = isRouteErrorResponse(error) && error.status === 404;
  if (!notFound) console.error(error);
  return (
    <div className="flex min-h-screen items-center justify-center bg-white px-4 font-sans text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <div className="w-full max-w-lg" data-testid="route-error">
        <EmptyState
          icon={notFound ? FileQuestion : TriangleAlert}
          title={notFound ? t("Page not found") : t("Something went wrong")}
        >
          {notFound ? (
            isServerPath(pathname) ? (
              <p>
                {t(
                  "This address is provided by the Abstimmbar server, but the request did not reach it. The web server in front of Abstimmbar probably does not forward this path (or still uses an outdated configuration). Please let the administrators of this installation know.",
                )}
              </p>
            ) : (
              <p>{t("The page you requested does not exist (anymore). Please check the address.")}</p>
            )
          ) : (
            <p>{t("The page could not be displayed. Please reload it; if the problem persists, let the administrators know.")}</p>
          )}
          <p className="mt-4">
            <a
              href="/"
              className="font-medium text-brand-700 underline hover:text-brand-800 dark:text-brand-300"
            >
              {t("To the start page")}
            </a>
          </p>
        </EmptyState>
      </div>
    </div>
  );
}
