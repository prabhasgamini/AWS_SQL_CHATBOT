// Where the FastAPI server runs. Set BACKEND_URL in frontend/.env.local if it isn't on this address.
export const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

// Name of the httpOnly cookie that carries the sign-in token. Browser scripts can't read it.
export const SESSION_COOKIE = "session";
