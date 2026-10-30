import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SQL Knowledge Base",
  description: "Ask questions about DTRs, consumers and smart meter data",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
