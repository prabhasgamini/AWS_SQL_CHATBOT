"use client";

import { useEffect, useRef, useState } from "react";
import Sidebar from "@/components/Sidebar";
import Composer from "@/components/Composer";
import MessageView from "@/components/MessageView";
import ErrorBoundary from "@/components/ErrorBoundary";
import { loadSessions, newSession, saveSessions, titleFrom } from "@/lib/sessions";
import type { ChatApiResponse, Message, Session, User } from "@/lib/types";

const ADMIN_SUGGESTIONS = [
  "Which DTRs are overloaded this week?",
  "What is the power factor of Mahesh Patel?",
  "Show the top consumers on DTR-1001",
  "Which consumers have a poor power factor?",
];

const USER_SUGGESTIONS = [
  "What is my power factor?",
  "How much energy did I use this week?",
  "What share of my transformer's load am I?",
  "Show my connection details",
];

const toReply = (data: ChatApiResponse): Message => ({
  id: crypto.randomUUID(),
  role: "assistant",
  content: data.response,
  sql: data.generated_sql,
  columns: data.columns,
  data: data.data,
  truncated: data.truncated,
  calculations: data.calculations,
  timings: data.timings,
  tokens: data.token_usage,
});

const errorReply = (err: unknown): Message => ({
  id: crypto.randomUUID(),
  role: "assistant",
  isError: true,
  content: err instanceof Error ? err.message : "Something went wrong.",
});

const goToLogin = () => {
  window.location.href = "/login";
};

// reads the JSON body and turns a non-2xx answer into an Error with the server's message
async function post(url: string, payload: object): Promise<ChatApiResponse> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (res.status === 401) {
    goToLogin();
    throw new Error("Please sign in.");
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
  return body as ChatApiResponse;
}

export default function Home() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [freshId, setFreshId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const active = sessions.find((s) => s.id === activeId) ?? null;

  // Find out who is signed in, load their chats, and greet them once per login.
  // localStorage only exists in the browser, so all of this runs after mount.
  useEffect(() => {
    let cancelled = false;

    (async () => {
      const res = await fetch("/api/auth/me").catch(() => null);
      if (!res || res.status === 401) return goToLogin();
      if (!res.ok || cancelled) return;
      const me = (await res.json()).user as User;

      const stored = loadSessions(me.username);
      setUser(me);
      setSessions(stored);
      setActiveId(stored[0]?.id ?? null);
      setReady(true);

      if (sessionStorage.getItem("welcomed") === me.username) return;
      sessionStorage.setItem("welcomed", me.username); // set first, so a double effect run can't greet twice
      welcome();
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (ready && user) saveSessions(user.username, sessions);
  }, [sessions, ready, user]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [active?.messages.length, loading]);

  const updateSession = (id: string, change: (s: Session) => Session) =>
    setSessions((prev) => prev.map((s) => (s.id === id ? change(s) : s)));

  const startNewChat = () => {
    setActiveId(null);
    setSidebarOpen(false);
  };

  const deleteSession = (id: string) => {
    setSessions((prev) => prev.filter((s) => s.id !== id));
    if (id === activeId) setActiveId(null);
    fetch(`/api/sessions/${id}`, { method: "DELETE" }).catch(() => {});
  };

  // The automatic first message: the backend looks up this user's details and the model writes the greeting.
  const welcome = async () => {
    const created = newSession();
    created.title = "Welcome";
    setSessions((prev) => [created, ...prev]);
    setActiveId(created.id);
    setLoading(true);

    let reply: Message;
    try {
      reply = toReply(await post("/api/welcome", { session_id: created.id }));
    } catch (err) {
      reply = errorReply(err);
    }
    setFreshId(reply.id);
    updateSession(created.id, (s) => ({ ...s, messages: [reply], updatedAt: Date.now() }));
    setLoading(false);
  };

  const signOut = async () => {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
    sessionStorage.removeItem("welcomed");
    goToLogin();
  };

  const send = async (text: string) => {
    let sessionId = activeId;

    // first message of a brand new chat creates the session
    if (!sessionId) {
      const created = newSession();
      sessionId = created.id;
      setSessions((prev) => [created, ...prev]);
      setActiveId(created.id);
    }
    const id = sessionId;

    const userMsg: Message = { id: crypto.randomUUID(), role: "user", content: text };
    updateSession(id, (s) => ({
      ...s,
      title: s.messages.length === 0 ? titleFrom(text) : s.title,
      messages: [...s.messages, userMsg],
      updatedAt: Date.now(),
    }));

    setLoading(true);
    let reply: Message;

    try {
      reply = toReply(await post("/api/chat", { message: text, session_id: id }));
    } catch (err) {
      reply = errorReply(err);
    }

    setFreshId(reply.id);
    updateSession(id, (s) => ({ ...s, messages: [...s.messages, reply], updatedAt: Date.now() }));
    setLoading(false);
  };

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar
        sessions={sessions}
        activeId={activeId}
        open={sidebarOpen}
        onSelect={(id) => {
          setActiveId(id);
          setSidebarOpen(false);
        }}
        onNew={startNewChat}
        onDelete={deleteSession}
        onClose={() => setSidebarOpen(false)}
        user={user}
        onSignOut={signOut}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-line px-4 py-3 md:hidden">
          <button onClick={() => setSidebarOpen(true)} aria-label="Open sidebar" className="rounded p-1 hover:bg-line/50">
            <svg width="20" height="20" viewBox="0 0 20 20" stroke="currentColor" strokeWidth="1.6" fill="none">
              <path d="M3 5h14M3 10h14M3 15h14" />
            </svg>
          </button>
          <span className="truncate font-serif text-lg">{active?.title ?? "SQL Knowledge Base"}</span>
        </header>

        <div className="flex-1 overflow-y-auto">
          {!active || active.messages.length === 0 ? (
            <div className="mx-auto flex h-full max-w-2xl flex-col items-center justify-center px-6 text-center">
              <div className="mb-4 text-4xl text-accent">✻</div>
              <h1 className="font-serif text-3xl">What would you like to look up?</h1>
              <p className="mt-2 text-muted">
                Ask in plain English. I look it up, do the maths when needed, and show my working.
              </p>
              <div className="mt-8 grid w-full gap-2 sm:grid-cols-2">
                {(user?.role === "admin" ? ADMIN_SUGGESTIONS : USER_SUGGESTIONS).map((q) => (
                  <button
                    key={q}
                    onClick={() => send(q)}
                    disabled={loading}
                    className="rounded-xl border border-line bg-panel px-4 py-3 text-left text-sm hover:border-accent/50"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-8 px-4 py-8">
              {active.messages.map((m) => (
                <ErrorBoundary key={m.id}>
                  <MessageView message={m} fresh={m.id === freshId} />
                </ErrorBoundary>
              ))}

              {loading && (
                <div className="flex items-center gap-3">
                  <div className="flex h-7 w-7 items-center justify-center rounded-full bg-accent text-sm text-white">
                    ✻
                  </div>
                  <div className="flex items-center gap-1.5" aria-label="Working on it">
                    {[0, 1, 2].map((i) => (
                      <span
                        key={i}
                        className="dot h-1.5 w-1.5 rounded-full bg-muted"
                        style={{ animationDelay: `${i * 0.18}s` }}
                      />
                    ))}
                  </div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        <Composer onSend={send} disabled={loading} />
      </main>
    </div>
  );
}
