import type { Session } from "./types";

// one history per person, so a shared browser never shows one user another user's chats
const keyFor = (username: string) => `sql-kb-sessions-v2:${username}`;
const MAX_SESSIONS = 40;

export function loadSessions(username: string): Session[] {
  try {
    const raw = window.localStorage.getItem(keyFor(username));
    return raw ? (JSON.parse(raw) as Session[]) : [];
  } catch {
    return [];
  }
}

export function saveSessions(username: string, sessions: Session[]) {
  try {
    window.localStorage.setItem(keyFor(username), JSON.stringify(sessions.slice(0, MAX_SESSIONS)));
  } catch {
    // storage full or blocked, history just won't survive a refresh
  }
}

export function newSession(): Session {
  return { id: crypto.randomUUID(), title: "New chat", messages: [], updatedAt: Date.now() };
}

export function titleFrom(text: string) {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > 42 ? clean.slice(0, 42) + "…" : clean;
}
