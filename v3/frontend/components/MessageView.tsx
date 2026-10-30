"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { Message } from "@/lib/types";
import SqlBlock from "./SqlBlock";
import DataTable from "./DataTable";
import CalcBlock from "./CalcBlock";

// Reveals text a few characters at a time so a finished answer still feels like it is streaming in.
function useTypewriter(text: string, enabled: boolean) {
  const [count, setCount] = useState(enabled ? 0 : text.length);

  useEffect(() => {
    if (!enabled) {
      setCount(text.length);
      return;
    }
    setCount(0);
    const step = Math.max(2, Math.ceil(text.length / 100));
    const timer = setInterval(() => {
      setCount((c) => {
        const next = c + step;
        if (next >= text.length) {
          clearInterval(timer);
          return text.length;
        }
        return next;
      });
    }, 18);
    return () => clearInterval(timer);
  }, [text, enabled]);

  return text.slice(0, count);
}

function Metrics({ message }: { message: Message }) {
  if (!message.timings) return null;
  const seconds = (message.timings.total_ms / 1000).toFixed(1);
  const tokens = message.tokens?.total_tokens ?? 0;
  const t = message.timings;

  return (
    <p
      className="text-xs text-muted"
      title={`guardrails ${t.guardrails_ms} ms · model ${t.llm_ms} ms · sql ${t.sql_ms} ms`}
    >
      {seconds}s{tokens > 0 ? ` · ${tokens.toLocaleString()} tokens` : ""}
    </p>
  );
}

export default function MessageView({ message, fresh }: { message: Message; fresh: boolean }) {
  const isUser = message.role === "user";
  const shown = useTypewriter(message.content, !isUser && fresh);
  const finished = shown.length === message.content.length;

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl bg-sidebar px-4 py-2.5 text-[15px] leading-relaxed">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3">
      <div
        className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent text-sm text-white"
        aria-hidden
      >
        ✻
      </div>

      <div className="min-w-0 flex-1 space-y-3">
        {message.isError ? (
          <div className="rounded-lg border border-red-400/40 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-300">
            {message.content}
          </div>
        ) : (
          <div className="md font-serif text-[16.5px] leading-[1.7]">
            <ReactMarkdown>{shown}</ReactMarkdown>
          </div>
        )}

        {finished && message.calculations?.map((c, i) => <CalcBlock key={i} calc={c} />)}
        {finished && message.sql && <SqlBlock sql={message.sql} />}
        {finished && message.data && message.data.length > 0 && (
          <DataTable columns={message.columns ?? []} rows={message.data} truncated={message.truncated} />
        )}
        {finished && <Metrics message={message} />}
      </div>
    </div>
  );
}
