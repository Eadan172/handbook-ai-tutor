import { create } from "zustand";
import { persist } from "zustand/middleware";

type User = { id: string; email: string };

type AuthState = {
  token: string | null;
  user: User | null;
  setToken: (token: string | null) => void;
  setUser: (user: User | null) => void;
  logout: () => void;
};

export const useAuth = create<AuthState>()(
  persist(
    (set) => ({
      token: null,
      user: null,
      setToken: (token) => set({ token }),
      setUser: (user) => set({ user }),
      logout: () => set({ token: null, user: null }),
    }),
    { name: "tutor-auth" }
  )
);

export const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

/**
 * fetch() rejects only on a *network* failure — the API is not reachable at all
 * (not started, wrong port, preflight refused). The browser's own wording is
 * "Failed to fetch", which tells the learner nothing about what to do; the most
 * common cause by far is simply that the backend window was closed.
 */
function unreachable(): Error {
  return new Error(
    `无法连接后端服务（${apiBase}）· Backend unreachable. ` +
      "请先启动后端：双击项目根目录的 start.vbs，然后刷新本页。",
  );
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = useAuth.getState().token;
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let res: Response;
  try {
    res = await fetch(`${apiBase}${path}`, { ...init, headers });
  } catch {
    throw unreachable();
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  try {
    return (await res.json()) as T;
  } catch {
    throw new Error(`后端返回了非 JSON 响应（${path}）· Malformed response from the API.`);
  }
}
