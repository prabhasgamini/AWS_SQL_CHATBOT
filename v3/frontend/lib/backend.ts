import { cookies } from "next/headers";
import { BACKEND_URL, SESSION_COOKIE } from "@/lib/config";

// Sends a request to FastAPI with the user's token from the httpOnly cookie.
// The token never reaches browser JavaScript, only these server routes see it.
export async function callBackend(path: string, init: { method?: string; body?: string } = {}) {
  const token = cookies().get(SESSION_COOKIE)?.value;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;

  try {
    const upstream = await fetch(`${BACKEND_URL}${path}`, {
      method: init.method ?? "GET",
      headers,
      body: init.body,
      cache: "no-store",
    });
    const text = await upstream.text();

    // an expired or revoked token: drop the cookie so the middleware sends the user to /login
    if (upstream.status === 401) cookies().delete(SESSION_COOKIE);

    return new Response(text, { status: upstream.status, headers: { "Content-Type": "application/json" } });
  } catch {
    return Response.json(
      { detail: `Can't reach the backend at ${BACKEND_URL}. Is uvicorn running?` },
      { status: 502 },
    );
  }
}
