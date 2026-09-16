// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** A file picker you can drag a file onto or click to choose. Single file. */
import { Upload } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export default function FileDropzone({
  accept,
  file,
  onFile,
  hint,
  className = "",
}: {
  accept: string;
  file: File | null;
  onFile: (file: File) => void;
  /** Small caption under the label, e.g. the accepted formats. */
  hint?: string;
  className?: string;
}) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  function pick(files: FileList | null) {
    const chosen = files?.[0];
    if (chosen) onFile(chosen);
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => inputRef.current?.click()}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          inputRef.current?.click();
        }
      }}
      onDragOver={(event) => {
        event.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragOver(false);
        pick(event.dataTransfer.files);
      }}
      className={
        "flex cursor-pointer flex-col items-center justify-center gap-1 rounded-xl border-2 border-dashed px-4 py-6 text-center text-sm transition-colors focus:outline-none focus:ring-1 focus:ring-brand-600 " +
        (dragOver
          ? "border-brand-500 bg-brand-50 dark:border-brand-500 dark:bg-brand-950/40"
          : "border-slate-300 hover:border-brand-400 dark:border-slate-700 dark:hover:border-brand-600") +
        (className ? ` ${className}` : "")
      }
    >
      <Upload aria-hidden className="h-5 w-5 text-slate-400" />
      {file ? (
        <span className="font-medium text-slate-700 dark:text-slate-200">{file.name}</span>
      ) : (
        <span className="text-slate-600 dark:text-slate-300">
          {t("Drag a file here or click to choose")}
        </span>
      )}
      {hint && <span className="text-xs text-slate-400">{hint}</span>}
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(event) => pick(event.target.files)}
      />
    </div>
  );
}
