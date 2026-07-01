import { NextResponse, type NextRequest } from "next/server";
import { getIronSession } from "iron-session";
import type { SessionData } from "@/lib/session";

// Routes that don't need a session.
const PUBLIC_PATHS = ["/login", "/api/auth/login"];

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  // Allow public routes and Next.js internals through unchecked.
  if (
    PUBLIC_PATHS.some((p) => pathname.startsWith(p)) ||
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon")
  ) {
    return NextResponse.next();
  }

  // getIronSession in middleware needs the raw request/response objects.
  const res = NextResponse.next();
  const session = await getIronSession<SessionData>(req, res, {
    password: process.env.SESSION_PASSWORD!,
    cookieName: "docmap-session",
  });

  if (!session.isLoggedIn) {
    return NextResponse.redirect(new URL("/login", req.url));
  }

  return res;
}

export const config = {
  // Run on every path except static assets.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
