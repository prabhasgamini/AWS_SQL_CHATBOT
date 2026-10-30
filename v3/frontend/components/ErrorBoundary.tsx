"use client";

import { Component, type ReactNode } from "react";

// If one message fails to render (odd data from the backend, say) we only lose that
// message, not the whole chat.
export default class ErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return (
        <div className="rounded-lg border border-line px-3 py-2 text-sm text-muted">
          This message couldn&apos;t be displayed.
        </div>
      );
    }
    return this.props.children;
  }
}
