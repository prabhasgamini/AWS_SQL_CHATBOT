import { callBackend } from "@/lib/backend";

export const dynamic = "force-dynamic";

export async function GET() {
  return callBackend("/api/auth/me");
}
