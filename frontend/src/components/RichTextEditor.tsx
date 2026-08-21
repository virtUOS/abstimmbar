// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** The one WYSIWYG editor (#49) for all formatted long-form fields: bold,
 * italic, lists, link, headings (H2/H3), images. Stores HTML; the backend
 * sanitizes to exactly this subset (common.html_sanitize) — anything else is
 * stripped. Short fields (titles, options) stay plain and do not use this. */
// Bold ships inside @tiptap/starter-kit (same pinned version); we import it
// directly only to override its parse rules — no extra dependency added.
import Bold from "@tiptap/extension-bold";
import Image from "@tiptap/extension-image";
import Link from "@tiptap/extension-link";
import { EditorContent, useEditor, type Editor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import {
  Bold as BoldIcon,
  Heading2,
  Heading3,
  ImagePlus,
  Italic as ItalicIcon,
  Link as LinkIcon,
  List,
  ListOrdered,
} from "lucide-react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api";

/** Bold that only recognises explicit <strong>/<b> tags. TipTap's default
 * also parses any `font-weight: 500–900` as bold — so text typed after a
 * DOM reparse or pasted from Word/PDF turned bold on its own. We bold only
 * via the toolbar (which emits <strong>, the one tag the backend keeps). */
const PlainBold = Bold.extend({
  parseHTML() {
    return [{ tag: "strong" }, { tag: "b" }];
  },
});

async function insertImageFile(editor: Editor, file: File, pos?: number) {
  const { url } = await api.uploadImage(file);
  const chain = editor.chain().focus();
  if (pos !== undefined) chain.insertContentAt(pos, { type: "image", attrs: { src: url } });
  else chain.setImage({ src: url });
  chain.run();
}

function ToolbarButton({
  active,
  label,
  onClick,
  children,
}: {
  active?: boolean;
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
      onMouseDown={(event) => event.preventDefault()}
      onClick={onClick}
      className={`rounded px-2 py-1 text-sm ${
        active ? "bg-brand-100 dark:bg-brand-900 text-brand-800 dark:text-brand-200" : "text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
      }`}
    >
      {children}
    </button>
  );
}

export default function RichTextEditor({
  value,
  onChange,
}: {
  value: string;
  onChange: (html: string) => void;
}) {
  const { t } = useTranslation();
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [2, 3] },
        blockquote: false,
        codeBlock: false,
        code: false,
        horizontalRule: false,
        link: false,
        bold: false,
      }),
      PlainBold,
      // Links may point anywhere; the backend forces rel="noopener". We do not
      // open a new tab, and we do not auto-link typed URLs (toolbar only).
      Link.configure({ openOnClick: false, autolink: false, HTMLAttributes: { rel: "noopener" } }),
      Image,
    ],
    content: value,
    onUpdate: ({ editor }) => onChange(editor.getHTML()),
    editorProps: {
      attributes: {
        class:
          // Match the single-line inputs' ink so typed text is crisp in both
          // themes (the editor otherwise inherits a dim slate-400/500).
          "text-slate-900 dark:text-slate-100 " +
          // The editable fills the frame edge-to-edge, so the global
          // :focus-visible ring (base.css) would bulge out past the border and
          // look wider than the toolbar. Suppress it — the container's
          // focus-within:border-brand-600 already signals focus.
          "min-h-28 max-h-[420px] overflow-y-auto rounded-b-lg px-3 py-2 " +
          "focus:outline-none focus-visible:outline-none focus-visible:ring-0 focus-visible:ring-offset-0 " +
          "[&_img]:max-w-full [&_img]:h-auto [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5 " +
          "[&_p]:my-1 [&_li]:my-0.5 [&_h2]:mt-2 [&_h2]:mb-1 [&_h2]:text-xl [&_h2]:font-bold " +
          "[&_h3]:mt-2 [&_h3]:mb-1 [&_h3]:text-base [&_h3]:font-semibold " +
          "[&_a]:text-brand-700 [&_a]:underline dark:[&_a]:text-brand-300",
      },
      handleDrop: (view, event) => {
        const file = event.dataTransfer?.files?.[0];
        if (file && file.type.startsWith("image/") && editor) {
          event.preventDefault();
          const at = view.posAtCoords({ left: event.clientX, top: event.clientY });
          void insertImageFile(editor, file, at?.pos);
          return true;
        }
        return false;
      },
    },
  });

  // Sync when the value changes from OUTSIDE (e.g. applying an AI rephrasing,
  // or switching the active language tab). The guard avoids clobbering the
  // cursor during normal typing (there the stored value already equals the
  // editor's HTML). emitUpdate:false so this settles without a second round
  // that would reset the caret to the top while the user is typing (#50).
  useEffect(() => {
    if (editor && value !== editor.getHTML()) {
      editor.commands.setContent(value, { emitUpdate: false });
    }
  }, [editor, value]);

  if (!editor) return null;

  function setLink() {
    if (!editor) return;
    const previous = (editor.getAttributes("link").href as string) || "";
    const url = window.prompt(t("Enter URL"), previous);
    if (url === null) return; // cancelled
    if (url === "") {
      editor.chain().focus().extendMarkRange("link").unsetLink().run();
      return;
    }
    editor.chain().focus().extendMarkRange("link").setLink({ href: url }).run();
  }

  return (
    <div className="rounded-lg border border-slate-300 dark:border-slate-700 focus-within:ring-2 focus-within:ring-brand-600 focus-within:ring-offset-2 focus-within:ring-offset-white dark:focus-within:ring-offset-slate-950">
      <div className="flex flex-nowrap gap-1 overflow-x-auto border-b border-slate-200 dark:border-slate-800 px-2 py-1">
        <ToolbarButton
          label={t("Bold")}
          active={editor.isActive("bold")}
          onClick={() => editor.chain().focus().toggleBold().run()}
        >
          <BoldIcon aria-hidden className="h-4 w-4" />
        </ToolbarButton>
        <ToolbarButton
          label={t("Italic")}
          active={editor.isActive("italic")}
          onClick={() => editor.chain().focus().toggleItalic().run()}
        >
          <ItalicIcon aria-hidden className="h-4 w-4" />
        </ToolbarButton>
        <ToolbarButton
          label={t("Heading (large)")}
          active={editor.isActive("heading", { level: 2 })}
          onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
        >
          <Heading2 aria-hidden className="h-4 w-4" />
        </ToolbarButton>
        <ToolbarButton
          label={t("Heading (small)")}
          active={editor.isActive("heading", { level: 3 })}
          onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
        >
          <Heading3 aria-hidden className="h-4 w-4" />
        </ToolbarButton>
        <ToolbarButton
          label={t("Bulleted list")}
          active={editor.isActive("bulletList")}
          onClick={() => editor.chain().focus().toggleBulletList().run()}
        >
          <List aria-hidden className="h-4 w-4" />
        </ToolbarButton>
        <ToolbarButton
          label={t("Numbered list")}
          active={editor.isActive("orderedList")}
          onClick={() => editor.chain().focus().toggleOrderedList().run()}
        >
          <ListOrdered aria-hidden className="h-4 w-4" />
        </ToolbarButton>
        <ToolbarButton
          label={t("Link")}
          active={editor.isActive("link")}
          onClick={setLink}
        >
          <LinkIcon aria-hidden className="h-4 w-4" />
        </ToolbarButton>
        <label
          className="flex cursor-pointer items-center rounded px-2 py-1 text-sm text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
          title={t("Insert image (or drag and drop)")}
        >
          <ImagePlus aria-hidden className="h-4 w-4" />
          <input
            type="file"
            accept="image/*"
            className="sr-only"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void insertImageFile(editor, file);
              event.target.value = "";
            }}
          />
        </label>
      </div>
      <EditorContent editor={editor} />
    </div>
  );
}
