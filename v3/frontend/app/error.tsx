"use client";

// Next.js picks this up automatically as the error boundary for the whole page.
export default function GlobalError({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-3 px-6 text-center">
      <h2 className="font-serif text-2xl">Something went wrong</h2>
      <p className="max-w-md text-sm text-muted">{error.message}</p>
      <button
        onClick={reset}
        className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90"
      >
        Try again
      </button>
    </div>
  );
}
