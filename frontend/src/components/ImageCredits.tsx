import { Fragment, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { formatCreditParts, visibleImageCredits } from "../imageCredits";
import type { ImageCredit } from "../api";

/** One muted credit line ("Bild: „Titel“ von Autor, CC BY 4.0") for the
 *  images that are visible in the shown question (#336). Renders nothing when
 *  there is none. `links=false` (presenter/beamer) prints plain text. */
export function ImageCredits({
  credits,
  html,
  optionImages = [],
  links = true,
  className = "",
}: {
  credits?: ImageCredit[];
  html: string;
  optionImages?: (string | undefined)[];
  links?: boolean;
  className?: string;
}) {
  const { t, i18n } = useTranslation();
  const shown = visibleImageCredits(credits, html, optionImages);
  if (!shown.length) return null;
  const part = (text: string, url?: string): ReactNode =>
    links && url ? (
      <a href={url} target="_blank" rel="noopener noreferrer" className="underline">
        {text}
      </a>
    ) : (
      text
    );
  return (
    <p data-testid="image-credits" className={`text-sm text-slate-500 dark:text-slate-400 ${className}`}>
      {shown.length > 1 ? t("Images:") : t("Image:")}{" "}
      {shown.map((c, i) => {
        const p = formatCreditParts(c, t, i18n.language);
        const nodes: ReactNode[] = [];
        if (p.title) {
          nodes.push(<Fragment key="t">{part(p.title, p.source)}</Fragment>);
          if (p.author) nodes.push(` ${t("by")} ${p.author}`);
        } else if (p.author) {
          nodes.push(<Fragment key="a">{part(p.author, p.source)}</Fragment>);
        }
        if (p.license) {
          if (nodes.length) nodes.push(", ");
          nodes.push(<Fragment key="l">{part(p.license, p.licenseUrl)}</Fragment>);
        }
        return (
          <Fragment key={c.id}>
            {i > 0 && " · "}
            {nodes.map((n, j) => (
              <Fragment key={j}>{n}</Fragment>
            ))}
          </Fragment>
        );
      })}
    </p>
  );
}
