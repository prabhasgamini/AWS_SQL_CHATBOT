import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE } from "@/lib/config";

// Anything except the login page and the login call needs the session cookie.
// This only checks that a cookie exists; the backend decides whether the token is still valid.
export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  const open = pathname === "/login" || pathname === "/api/auth/login";
  if (open || req.cookies.get(SESSION_COOKIE)) return NextResponse.next();

  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ detail: "Please sign in." }, { status: 401 });
  }
  return NextResponse.redirect(new URL("/login", req.url));
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
