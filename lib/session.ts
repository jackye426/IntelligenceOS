import { getIronSession, type SessionOptions as IronSessionOptions } from "iron-session";
import { cookies } from "next/headers";

export interface SessionData {
  isLoggedIn: boolean;
}

const sessionOptions: IronSessionOptions = {
  password: process.env.SESSION_PASSWORD!,
  cookieName: "docmap-session",
  cookieOptions: {
    // Keep the cookie server-only and secure in production.
    secure: process.env.NODE_ENV === "production",
    httpOnly: true,
    sameSite: "lax",
    maxAge: 60 * 60 * 24 * 7, // 7 days
  },
};

export async function getSession() {
  const cookieStore = await cookies();
  return getIronSession<SessionData>(cookieStore, sessionOptions);
}
