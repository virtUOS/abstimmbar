// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Staff-only site administration: branding (logo + landing text) and the
 * footer page CMS (Impressum, Datenschutz, free pages). Guarded by is_staff;
 * every endpoint is additionally server-side gated (accounts.IsAdmin). */
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronUp, FileText, Lock, Radio, Trash2 } from "lucide-react";
import { api, type LtiPlatform, type LtiToolInfo, type ManagePage, type ManageSite } from "../api";
import { useApp } from "../App";
import { localizedText, type LocalizedText } from "@basicbar/ui";
import TranslatableField from "../components/TranslatableField";
import { Button, ConfirmInline, EmptyState, Field, InfoHint, Select, TextInput } from "../components/ui";

function slugify(value: string) {
  return value
    .toLowerCase()
    .replace(/[äàá]/g, "a").replace(/[öòó]/g, "o").replace(/[üùú]/g, "u")
    .replace(/ß/g, "ss")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

export default function AdminPage() {
  const { t } = useTranslation();
  const { whoami } = useApp();
  if (!whoami) return null;
  if (!whoami.is_staff) {
    return (
      <EmptyState icon={Lock} title={t("No access")}>
        {t("This area is only for administrators.")}
      </EmptyState>
    );
  }
  return (
    <div className="space-y-12">
      <div>
        <nav className="mb-4 text-sm text-slate-500 dark:text-slate-400">
          <Link to="/" className="hover:text-brand-700 dark:hover:text-brand-300">
            {t("My rooms")}
          </Link>
        </nav>
        <h1 className="text-2xl font-bold">{t("Manage website")}</h1>
      </div>
      <BrandingSection />
      <PagesSection />
      <LtiPlatformsSection />
    </div>
  );
}

function BrandingSection() {
  const { t } = useTranslation();
  const [site, setSite] = useState<ManageSite | null>(null);
  const [text, setText] = useState<LocalizedText>("");
  const [closing, setClosing] = useState<LocalizedText>("");
  const [aiNotice, setAiNotice] = useState<LocalizedText>("");
  const [aiNoticePage, setAiNoticePage] = useState("");
  const [aiNoticeUrl, setAiNoticeUrl] = useState("");
  const [pages, setPages] = useState<ManagePage[]>([]);
  const [saved, setSaved] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void api.getManageSite().then((data) => {
      setSite(data);
      setText(data.landing_text);
      setClosing(data.closing_info);
      setAiNotice(data.ai_notice);
      setAiNoticePage(data.ai_notice_page ?? "");
      setAiNoticeUrl(data.ai_notice_url);
    });
    void api.listManagePages().then(setPages);
  }, []);

  async function saveText() {
    const updated = await api.updateSite({
      landing_text: text,
      closing_info: closing,
      ai_notice: aiNotice,
      ai_notice_page: aiNoticePage || null,
      ai_notice_url: aiNoticeUrl,
    });
    setSite(updated);
    setSaved(true);
    window.setTimeout(() => setSaved(false), 1500);
  }

  async function upload(file: File) {
    setSite(await api.uploadLogo(file));
  }

  async function removeLogo() {
    await api.deleteLogo();
    setSite(site ? { ...site, logo: null } : site);
  }

  if (!site) return null;

  return (
    <section>
      <h2 className="mb-4 text-lg font-semibold">{t("Appearance")}</h2>

      <Field label={t("Logo (shown top left; PNG, JPG or SVG)")}>
        <div className="flex flex-wrap items-center gap-4">
          {site.logo ? (
            <img
              src={site.logo}
              alt={t("Current logo")}
              className="h-10 w-auto max-w-[180px] rounded border border-slate-200 bg-white p-1 dark:border-slate-700"
            />
          ) : (
            <span className="text-sm text-slate-400">{t("No logo — “abstimmBAR” wordmark")}</span>
          )}
          <input
            ref={fileInput}
            type="file"
            accept="image/*,.svg"
            className="sr-only"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void upload(file);
              event.target.value = "";
            }}
          />
          <Button onClick={() => fileInput.current?.click()}>
            {site.logo ? t("Replace logo") : t("Upload logo")}
          </Button>
          {site.logo && (
            <Button variant="danger" onClick={() => void removeLogo()}>
              {t("Remove")}
            </Button>
          )}
        </div>
      </Field>

      <div className="mt-6 max-w-2xl">
        <div className="mb-4">
          <TranslatableField
            variant="rich"
            label={t("Landing page text before login")}
            value={text}
            onChange={setText}
          />
        </div>
        <TranslatableField
          variant="rich"
          label={t("Closing info for all rooms")}
          value={closing}
          onChange={setClosing}
          placeholder={t("Shown to participants after every vote — e.g. contact, feedback link …")}
        />
        <div className="mt-4">
          <TranslatableField
            label={t("AI privacy notice")}
            value={aiNotice}
            onChange={setAiNotice}
            placeholder={t("e.g. An external model processes uploaded material.")}
            hint={t("Shown as a one-time banner while the AI features are available. Leave empty for no banner.")}
          />
        </div>
        <div className="mt-3">
          <Field label={t("Privacy policy page (internal)")}>
            <Select
              value={aiNoticePage}
              onChange={(event) => setAiNoticePage(event.target.value)}
            >
              <option value="">{t("— none —")}</option>
              {pages
                .filter((page) => page.is_published)
                .map((page) => (
                  <option key={page.slug} value={page.slug}>
                    {localizedText(page.title)}
                  </option>
                ))}
            </Select>
          </Field>
        </div>
        <div className="mt-3">
          <Field label={t("…or external privacy policy URL")}>
            <TextInput
              type="url"
              value={aiNoticeUrl}
              onChange={(event) => setAiNoticeUrl(event.target.value)}
              placeholder="https://…"
              disabled={!!aiNoticePage}
            />
          </Field>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <Button variant="primary" onClick={() => void saveText()}>
            {t("Save")}
          </Button>
          <span aria-live="polite" className="text-xs text-brand-700 dark:text-brand-300">
            {saved ? t("Saved.") : ""}
          </span>
        </div>
      </div>
    </section>
  );
}

function PagesSection() {
  const { t } = useTranslation();
  const [pages, setPages] = useState<ManagePage[] | null>(null);
  const [editing, setEditing] = useState<ManagePage | "new" | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);

  const reload = () => api.listManagePages().then(setPages);
  useEffect(() => {
    void reload();
  }, []);

  async function move(index: number, delta: number) {
    if (!pages) return;
    const next = [...pages];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setPages(next);
    await api.reorderPages(next.map((p) => p.id));
  }

  async function handleDelete(id: number) {
    await api.deletePage(id);
    setConfirmDelete(null);
    await reload();
  }

  if (!pages) return null;

  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t("Pages (footer)")}</h2>
        {editing === null && (
          <div className="flex items-center gap-2">
            <InfoHint
              text={t(
                "Info pages shown in the site footer (e.g. imprint or privacy policy). They belong to the whole site — not to a single room, question set or question.",
              )}
            />
            <Button variant="primary" onClick={() => setEditing("new")}>
              + {t("New page")}
            </Button>
          </div>
        )}
      </div>

      {editing !== null && (
        <PageForm
          page={editing === "new" ? null : editing}
          onCancel={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void reload();
          }}
        />
      )}

      {pages.length === 0 ? (
        <EmptyState icon={FileText} title={t("No pages yet")}>
          {t(
            "Legal notice and privacy policy are created as drafts on first start — edit and publish them here.",
          )}
        </EmptyState>
      ) : (
        <ul className="divide-y divide-slate-200 rounded-2xl border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
          {pages.map((page, index) => (
            <li key={page.id} className="flex items-center gap-3 px-4 py-3">
              <div className="flex flex-col">
                <button
                  type="button"
                  aria-label={t("Move up")}
                  disabled={index === 0}
                  onClick={() => void move(index, -1)}
                  className="text-slate-400 hover:text-slate-700 disabled:opacity-30 dark:hover:text-slate-200"
                >
                  <ChevronUp aria-hidden className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  aria-label={t("Move down")}
                  disabled={index === pages.length - 1}
                  onClick={() => void move(index, 1)}
                  className="text-slate-400 hover:text-slate-700 disabled:opacity-30 dark:hover:text-slate-200"
                >
                  <ChevronDown aria-hidden className="h-4 w-4" />
                </button>
              </div>
              <div className="min-w-0 flex-1">
                <span className="font-medium text-slate-900 dark:text-slate-100">
                  {localizedText(page.title)}
                </span>
                <span className="ml-2 font-mono text-xs text-slate-400">/{page.slug}</span>
                <div className="mt-0.5 flex gap-1.5">
                  <Badge on={page.is_published} on_label={t("Published")} off_label={t("Draft")} />
                </div>
              </div>
              <Button onClick={() => setEditing(page)}>{t("Edit")}</Button>
              {confirmDelete === page.id ? (
                <ConfirmInline
                  message={t("Delete page?")}
                  onConfirm={() => void handleDelete(page.id)}
                  onCancel={() => setConfirmDelete(null)}
                />
              ) : (
                <Button
                  variant="ghost"
                  aria-label={t("Delete {{title}}", { title: localizedText(page.title) })}
                  onClick={() => setConfirmDelete(page.id)}
                >
                  <Trash2 aria-hidden className="h-4 w-4" />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** LTI 1.3 platform registration (M4): connect LMS instances that may
 * launch into abstimmbar. Modeled on PagesSection (list + add/edit form +
 * delete confirm), plus a read-only panel with this deployment's endpoints. */
function LtiPlatformsSection() {
  const { t } = useTranslation();
  const [platforms, setPlatforms] = useState<LtiPlatform[] | null>(null);
  const [toolInfo, setToolInfo] = useState<LtiToolInfo | null>(null);
  const [editing, setEditing] = useState<LtiPlatform | "new" | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);

  const reload = () => api.listLtiPlatforms().then((data) => setPlatforms(data.results));
  useEffect(() => {
    void reload();
    void api.getLtiToolInfo().then(setToolInfo);
  }, []);

  async function handleDelete(id: number) {
    await api.deleteLtiPlatform(id);
    setConfirmDelete(null);
    await reload();
  }

  async function toggleActive(platform: LtiPlatform) {
    await api.updateLtiPlatform(platform.id, { is_active: !platform.is_active });
    await reload();
  }

  if (!platforms) return null;

  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t("LTI platforms")}</h2>
        {editing === null && (
          <Button variant="primary" onClick={() => setEditing("new")}>
            + {t("Add platform")}
          </Button>
        )}
      </div>

      {toolInfo && (
        <div className="mb-4 max-w-2xl rounded-2xl border border-slate-200 p-4 dark:border-slate-800">
          <h3 className="mb-2 font-semibold">{t("Tool endpoints")}</h3>
          <p className="mb-3 text-sm text-slate-500 dark:text-slate-400">
            {t("Enter these URLs in your LMS (see the guide).")}
          </p>
          <div className="grid gap-2">
            <Field label={t("Initiate login URL")}>
              <TextInput readOnly value={toolInfo.login_url} onFocus={(e) => e.target.select()} />
            </Field>
            <Field label={t("Launch URL")}>
              <TextInput readOnly value={toolInfo.launch_url} onFocus={(e) => e.target.select()} />
            </Field>
            <Field label={t("Keyset URL")}>
              <TextInput readOnly value={toolInfo.jwks_url} onFocus={(e) => e.target.select()} />
            </Field>
            <Field label={t("Icon URL")}>
              <TextInput readOnly value={toolInfo.icon_url} onFocus={(e) => e.target.select()} />
              <p className="mt-1 text-xs text-slate-400 dark:text-slate-500">
                {t("Enter as the tool's icon URL in your LMS.")}
              </p>
            </Field>
          </div>
        </div>
      )}

      {editing !== null && (
        <LtiPlatformForm
          platform={editing === "new" ? null : editing}
          onCancel={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void reload();
          }}
        />
      )}

      {platforms.length === 0 ? (
        <EmptyState icon={Radio} title={t("No platforms yet")}>
          {t("Register the LMS instances that may launch into abstimmbar here.")}
        </EmptyState>
      ) : (
        <ul className="divide-y divide-slate-200 rounded-2xl border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
          {platforms.map((platform) => (
            <li key={platform.id} className="flex items-center gap-3 px-4 py-3">
              <div className="min-w-0 flex-1">
                <span className="font-medium text-slate-900 dark:text-slate-100">
                  {platform.name}
                </span>
                <span className="ml-2 font-mono text-xs text-slate-400">{platform.issuer}</span>
                <div className="mt-0.5 flex gap-1.5">
                  <Badge on={platform.is_active} on_label={t("Active")} off_label={t("Inactive")} />
                  {platform.link_by_email && (
                    <Badge on on_label={t("Link users by email")} off_label="" />
                  )}
                </div>
              </div>
              <Button onClick={() => void toggleActive(platform)}>
                {platform.is_active ? t("Deactivate") : t("Activate")}
              </Button>
              <Button onClick={() => setEditing(platform)}>{t("Edit")}</Button>
              {confirmDelete === platform.id ? (
                <ConfirmInline
                  message={t("Delete platform?")}
                  onConfirm={() => void handleDelete(platform.id)}
                  onCancel={() => setConfirmDelete(null)}
                />
              ) : (
                <Button
                  variant="ghost"
                  aria-label={t("Delete {{title}}", { title: platform.name })}
                  onClick={() => setConfirmDelete(platform.id)}
                >
                  <Trash2 aria-hidden className="h-4 w-4" />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function LtiPlatformForm({
  platform,
  onCancel,
  onSaved,
}: {
  platform: LtiPlatform | null;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(platform?.name ?? "");
  const [issuer, setIssuer] = useState(platform?.issuer ?? "");
  const [clientId, setClientId] = useState(platform?.client_id ?? "");
  const [authLoginUrl, setAuthLoginUrl] = useState(platform?.auth_login_url ?? "");
  const [authTokenUrl, setAuthTokenUrl] = useState(platform?.auth_token_url ?? "");
  const [keySetUrl, setKeySetUrl] = useState(platform?.key_set_url ?? "");
  const [deploymentIds, setDeploymentIds] = useState(
    platform?.deployment_ids.join(", ") ?? "",
  );
  // On add, default to true — but the warning below makes the trade-off clear.
  const [linkByEmail, setLinkByEmail] = useState(platform?.link_by_email ?? true);
  const [isActive, setIsActive] = useState(platform?.is_active ?? true);
  const [error, setError] = useState("");

  async function save() {
    setError("");
    const data = {
      name,
      issuer,
      client_id: clientId,
      auth_login_url: authLoginUrl,
      auth_token_url: authTokenUrl,
      key_set_url: keySetUrl,
      deployment_ids: deploymentIds.split(",").map((s) => s.trim()).filter(Boolean),
      link_by_email: linkByEmail,
      is_active: isActive,
    };
    try {
      if (platform) await api.updateLtiPlatform(platform.id, data);
      else await api.createLtiPlatform(data);
      onSaved();
    } catch (err) {
      try {
        const parsed = JSON.parse((err as Error).message);
        const value = parsed.detail ?? Object.values(parsed)[0];
        setError(Array.isArray(value) ? value[0] : String(value));
      } catch {
        setError(String(err));
      }
    }
  }

  return (
    <div className="mb-6 max-w-2xl rounded-2xl border border-brand-200 bg-brand-50/50 p-4 dark:border-brand-900 dark:bg-brand-950/40">
      <h3 className="mb-3 font-semibold">{platform ? t("Edit platform") : t("Add platform")}</h3>
      <div className="grid gap-3">
        <Field label={t("Name")}>
          <TextInput value={name} onChange={(e) => setName(e.target.value)} required />
        </Field>
        <Field label={t("Issuer")}>
          <TextInput value={issuer} onChange={(e) => setIssuer(e.target.value)} required />
        </Field>
        <Field label={t("Client ID")}>
          <TextInput value={clientId} onChange={(e) => setClientId(e.target.value)} required />
        </Field>
        <Field label={t("Auth login URL")}>
          <TextInput value={authLoginUrl} onChange={(e) => setAuthLoginUrl(e.target.value)} required />
        </Field>
        <Field label={t("Auth token URL")}>
          <TextInput value={authTokenUrl} onChange={(e) => setAuthTokenUrl(e.target.value)} required />
        </Field>
        <Field label={t("Keyset URL")}>
          <TextInput value={keySetUrl} onChange={(e) => setKeySetUrl(e.target.value)} required />
        </Field>
        <Field label={t("Deployment IDs (comma-separated)")}>
          <TextInput value={deploymentIds} onChange={(e) => setDeploymentIds(e.target.value)} />
        </Field>
        <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
          <input
            type="checkbox"
            checked={linkByEmail}
            onChange={(event) => setLinkByEmail(event.target.checked)}
            className="h-4 w-4 rounded border-slate-300 accent-brand-600 dark:border-slate-700"
          />
          {t("Link users by email")}
        </label>
        {linkByEmail && (
          <p className="text-sm text-amber-700 dark:text-amber-400">
            {t(
              "The LMS becomes the authority for account matching — enable only for trusted LMS.",
            )}
          </p>
        )}
        <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
          <input
            type="checkbox"
            checked={isActive}
            onChange={(event) => setIsActive(event.target.checked)}
            className="h-4 w-4 rounded border-slate-300 accent-brand-600 dark:border-slate-700"
          />
          {t("Active")}
        </label>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <div className="flex gap-2">
          <Button variant="primary" onClick={() => void save()}>
            {t("Save")}
          </Button>
          <Button variant="ghost" onClick={onCancel}>
            {t("Cancel")}
          </Button>
        </div>
      </div>
    </div>
  );
}

function Badge({
  on,
  on_label,
  off_label,
}: {
  on: boolean;
  on_label: string;
  off_label: string;
}) {
  const label = on ? on_label : off_label;
  if (!label) return null;
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
        on
          ? "bg-brand-100 text-brand-800 dark:bg-brand-900 dark:text-brand-200"
          : "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400"
      }`}
    >
      {label}
    </span>
  );
}

function PageForm({
  page,
  onCancel,
  onSaved,
}: {
  page: ManagePage | null;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const [title, setTitle] = useState<LocalizedText>(page?.title ?? "");
  const [slug, setSlug] = useState(page?.slug ?? "");
  const [slugTouched, setSlugTouched] = useState(page !== null);
  const [body, setBody] = useState<LocalizedText>(page?.body ?? "");
  const [published, setPublished] = useState(page?.is_published ?? false);
  const [error, setError] = useState("");

  async function save() {
    setError("");
    const data = {
      title,
      slug: (slugTouched ? slug : slugify(localizedText(title))).trim(),
      body,
      is_published: published,
      // In Abstimmbar every info page is a footer page (#62): there are no
      // other page kinds, so this is always true rather than a UI toggle.
      show_in_footer: true,
    };
    try {
      if (page) await api.updatePage(page.id, data);
      else await api.createPage(data);
      onSaved();
    } catch (err) {
      try {
        const parsed = JSON.parse((err as Error).message);
        const value = parsed.detail ?? Object.values(parsed)[0];
        setError(Array.isArray(value) ? value[0] : String(value));
      } catch {
        setError(String(err));
      }
    }
  }

  return (
    <div className="mb-6 max-w-2xl rounded-2xl border border-brand-200 bg-brand-50/50 p-4 dark:border-brand-900 dark:bg-brand-950/40">
      <h3 className="mb-3 font-semibold">{page ? t("Edit page") : t("New page")}</h3>
      <div className="grid gap-3">
        <TranslatableField
          label={t("Title")}
          required
          value={title}
          onChange={(next) => {
            setTitle(next);
            if (!slugTouched) setSlug(slugify(localizedText(next)));
          }}
        />
        <div>
          <div className="mb-1 flex items-center gap-1.5">
            <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
              {t("Address (slug)")}
            </span>
            <InfoHint
              text={t(
                "The web address the page is reached under (e.g. …/imprint). Use short lowercase words without spaces — it is filled in from the title automatically.",
              )}
            />
          </div>
          <TextInput
            value={slug}
            onChange={(event) => {
              setSlugTouched(true);
              setSlug(event.target.value);
            }}
            placeholder={t("e.g. imprint")}
          />
        </div>
        <TranslatableField
          variant="rich"
          label={t("Content")}
          value={body}
          onChange={setBody}
        />
        <div className="flex items-center gap-1.5">
          <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
            <input
              type="checkbox"
              checked={published}
              onChange={(event) => setPublished(event.target.checked)}
              className="h-4 w-4 rounded border-slate-300 accent-brand-600 dark:border-slate-700"
            />
            {t("Published (otherwise draft only, not visible to the public)")}
          </label>
          <InfoHint
            text={t(
              "Only published pages are visible to visitors in the footer. Leave this off to keep the page as a draft while you work on it.",
            )}
          />
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <div className="flex gap-2">
          <Button variant="primary" onClick={() => void save()}>
            {t("Save")}
          </Button>
          <Button variant="ghost" onClick={onCancel}>
            {t("Cancel")}
          </Button>
        </div>
      </div>
    </div>
  );
}
