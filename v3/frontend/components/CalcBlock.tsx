"use client";

import { useState } from "react";
import type { Calculation } from "@/lib/types";

const pretty = (key: string) => key.replace(/_/g, " ");

function show(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number") return Number.isInteger(value) ? value.toLocaleString() : String(value);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

// Shows how a figure was worked out: the formula, the inputs and the result.
export default function CalcBlock({ calc }: { calc: Calculation }) {
  const [open, setOpen] = useState(false);
  const result = calc.result ?? {};

  return (
    <div className="rounded-lg border border-line bg-panel text-sm">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between px-3 py-2 text-left">
        <span>
          <span className="font-medium capitalize">{pretty(calc.metric ?? "calculation")}</span>
          {calc.headline && <span className="text-muted"> · {calc.headline}</span>}
        </span>
        <span className="text-muted">{open ? "−" : "+"}</span>
      </button>

      {open && (
        <div className="space-y-2 border-t border-line px-3 py-2">
          {calc.formula && <p className="font-mono text-xs">{calc.formula}</p>}

          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5">
            {Object.entries(calc.inputs ?? {}).map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-muted capitalize">{pretty(k)}</dt>
                <dd>{show(v)}</dd>
              </div>
            ))}
            {Object.entries(result)
              .filter(([, v]) => typeof v !== "object")
              .map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="font-medium capitalize">{pretty(k)}</dt>
                  <dd className="font-medium">{show(v)}</dd>
                </div>
              ))}
          </dl>

          {calc.assessment && <p>{calc.assessment}</p>}
          {calc.notes?.map((n, i) => (
            <p key={i} className="text-xs text-muted">{n}</p>
          ))}
        </div>
      )}
    </div>
  );
}
