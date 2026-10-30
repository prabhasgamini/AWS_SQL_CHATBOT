import { cookies } from "next/headers";
import { callBackend } from "@/lib/backend";
import { SESSION_COOKIE } from "@/lib/config";

export const dynamic = "force-dynamic";

export async function POST() {
  await callBackend("/api/auth/logout", { method: "POST" }); // revoke the token on the server
  cookies().delete(SESSION_COOKIE);
  return Response.json({ signed_out: true });
}
