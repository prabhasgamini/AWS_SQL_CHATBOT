import { callBackend } from "@/lib/backend";

export const dynamic = "force-dynamic";

// The automatic first message after login.
export async function POST(req: Request) {
  return callBackend("/api/welcome", { method: "POST", body: await req.text() });
}
