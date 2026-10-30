"use client";

import { useEffect, useRef, useState } from "react";

export default function Composer({
  onSend,
  disabled,
}: {
  onSend: (text: string) => void;
  disabled: boolean;
}) {
  const [text, setText] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);

  // grow with the content, up to a limit
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }, [text]);

  const submit = () => {
    const value = text.trim();
    if (!value || disabled) return;
    onSend(value);
    setText("");
  };

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-5">
      <div className="flex items-end gap-2 rounded-2xl border border-line bg-panel p-2 shadow-sm focus-within:border-accent/60">
        <textarea
          ref={box}
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="Ask about DTRs, consumers, smart meters…"
          className="max-h-52 flex-1 resize-none bg-transparent px-2 py-1.5 text-[15px] outline-none placeholder:text-muted"
        />
        <button
          onClick={submit}
          disabled={disabled || !text.trim()}
          aria-label="Send message"
          className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent text-white transition hover:opacity-90 disabled:opacity-30"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M8 13V3M3.5 7.5L8 3l4.5 4.5" />
          </svg>
        </button>
      </div>
      <p className="mt-2 text-center text-xs text-muted">
        Read-only access to a local sample database. Answers can be wrong, check the SQL.
      </p>
    </div>
  );
}
