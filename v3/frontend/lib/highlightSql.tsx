import type { ReactNode } from "react";

const KEYWORDS = new Set(
  (
    "select from where join left right inner outer on and or not in is null as group by order " +
    "limit offset having distinct count sum avg min max like between case when then else end " +
    "with union all desc asc exists over partition"
  ).split(" "),
);

// string | comment | number | word | anything else (whitespace, punctuation)
const TOKEN = /('(?:[^']|'')*')|(--[^\n]*)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z_0-9]*)|(\s+|.)/g;

export function highlightSql(sql: string): ReactNode[] {
  const out: ReactNode[] = [];
  let i = 0;

  for (const m of sql.matchAll(TOKEN)) {
    const [text, str, comment, num, word] = m;
    let cls = "";

    if (str) cls = "text-emerald-600 dark:text-emerald-400";
    else if (comment) cls = "italic text-muted";
    else if (num) cls = "text-amber-600 dark:text-amber-400";
    else if (word && KEYWORDS.has(word.toLowerCase())) cls = "font-medium text-accent";
    else if (word && sql[(m.index ?? 0) + text.length] === "(") cls = "text-sky-600 dark:text-sky-400";

    out.push(
      cls ? (
        <span key={i++} className={cls}>
          {text}
        </span>
      ) : (
        text
      ),
    );
  }
  return out;
}
