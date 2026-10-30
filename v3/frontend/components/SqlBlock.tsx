"use client";

import { useState } from "react";
import { highlightSql } from "@/lib/highlightSql";

export default function SqlBlock({ sql }: { sql: string }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard can be blocked, nothing to do */
    }
  };

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-panel">
      <div className="flex items-center justify-between px-3 py-2">
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-2 text-xs font-medium text-muted hover:text-ink"
          aria-expanded={open}
        >
          <svg
            width="12"
            height="12"
            viewBox="0 0 12 12"
            className={`transition-transform ${open ? "rotate-90" : ""}`}
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
          >
            <path d="M4 2l4 4-4 4" />
          </svg>
          SQL query
        </button>
        {open && (
          <button onClick={copy} className="text-xs text-muted hover:text-ink">
            {copied ? "Copied" : "Copy"}
          </button>
        )}
      </div>

      {open && (
        <pre className="overflow-x-auto border-t border-line px-4 py-3 font-mono text-[13px] leading-relaxed">
          <code>{highlightSql(sql)}</code>
        </pre>
      )}
    </div>
  );
}
