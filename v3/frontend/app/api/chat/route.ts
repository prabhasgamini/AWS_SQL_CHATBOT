import { callBackend } from "@/lib/backend";

// Thin proxy so the browser only talks to Next.js and the token stays in the cookie.
export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  return callBackend("/api/chat", { method: "POST", body: await req.text() });
}
