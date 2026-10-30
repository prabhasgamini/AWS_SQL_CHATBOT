import { cookies } from "next/headers";
import { BACKEND_URL, SESSION_COOKIE } from "@/lib/config";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND_URL}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: await req.text(),
      cache: "no-store",
    });
  } catch {
    return Response.json({ detail: `Can't reach the backend at ${BACKEND_URL}. Is uvicorn running?` }, { status: 502 });
  }

  const body = await upstream.json().catch(() => ({}));
  if (!upstream.ok) {
    return Response.json({ detail: body.detail ?? "Sign-in failed." }, { status: upstream.status });
  }

  cookies().set(SESSION_COOKIE, body.token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.COOKIE_SECURE === "true",
    path: "/",
    maxAge: body.expires_in,
  });
  // the token itself is not sent on to the browser
  return Response.json({ user: body.user });
}
