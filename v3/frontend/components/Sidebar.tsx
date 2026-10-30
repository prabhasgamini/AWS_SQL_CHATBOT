"use client";

import type { Session, User } from "@/lib/types";

export default function Sidebar({
  sessions,
  activeId,
  open,
  onSelect,
  onNew,
  onDelete,
  onClose,
  user,
  onSignOut,
}: {
  sessions: Session[];
  activeId: string | null;
  open: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onClose: () => void;
  user: User | null;
  onSignOut: () => void;
}) {
  return (
    <>
      {/* dark overlay on small screens */}
      {open && <div className="fixed inset-0 z-20 bg-black/40 md:hidden" onClick={onClose} />}

      <aside
        className={`fixed inset-y-0 left-0 z-30 flex w-72 flex-col border-r border-line bg-sidebar transition-transform md:static md:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center gap-2 px-4 pb-2 pt-4">
          <span className="font-serif text-xl">SQL Knowledge Base</span>
        </div>

        <div className="px-3 py-2">
          <button
            onClick={onNew}
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium text-accent hover:bg-line/50"
          >
            <span className="text-lg leading-none">+</span> New chat
          </button>
        </div>

        <p className="px-4 pb-1 pt-2 text-xs font-medium uppercase tracking-wide text-muted">Recents</p>

        <nav className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-4">
          {sessions.length === 0 && <p className="px-3 py-2 text-sm text-muted">No chats yet</p>}

          {sessions.map((s) => (
            <div
              key={s.id}
              className={`group flex items-center rounded-lg ${
                s.id === activeId ? "bg-line/70" : "hover:bg-line/40"
              }`}
            >
              <button
                onClick={() => onSelect(s.id)}
                className="min-w-0 flex-1 truncate px-3 py-2 text-left text-sm"
              >
                {s.title}
              </button>
              <button
                onClick={() => onDelete(s.id)}
                aria-label={`Delete chat ${s.title}`}
                className="mr-1 hidden rounded p-1 text-muted hover:text-ink group-hover:block"
              >
                <svg width="14" height="14" viewBox="0 0 14 14" stroke="currentColor" strokeWidth="1.6" fill="none">
                  <path d="M3 3l8 8M11 3l-8 8" />
                </svg>
              </button>
            </div>
          ))}
        </nav>

        {user && (
          <div className="flex items-center justify-between gap-2 border-t border-line px-4 py-3 text-sm">
            <div className="min-w-0">
              <p className="truncate font-medium">{user.display_name}</p>
              <p className="text-xs text-muted">{user.role === "admin" ? "Administrator" : `Consumer ${user.consumer_number}`}</p>
            </div>
            <button onClick={onSignOut} className="shrink-0 rounded px-2 py-1 text-muted hover:bg-line/50 hover:text-ink">
              Sign out
            </button>
          </div>
        )}
      </aside>
    </>
  );
}
