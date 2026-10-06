import { computed, reactive } from 'vue';

// Login minimal (workplan demo D7). Backend: /api/auth/login mengembalikan
// token bearer; endpoint yang mengubah data (enrollment, koreksi, kamera,
// pengaturan) butuh peran admin. Token disimpan di localStorage supaya tidak
// hilang saat halaman di-refresh; berakhir sendiri setelah AUTH_SESSION_HOURS.

export interface AuthUser {
  id: number;
  username: string;
  role: 'admin' | 'viewer' | string;
}

const STORAGE_KEY = 'ai-time-tracking.auth';

function load(): { token: string | null; user: AuthUser | null; expiresAt: number } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed?.token && (parsed.expiresAt ?? 0) * 1000 > Date.now()) return parsed;
    }
  } catch {
    // localStorage diblokir / isinya rusak: anggap belum login
  }
  return { token: null, user: null, expiresAt: 0 };
}

const state = reactive(load());

function persist() {
  try {
    if (state.token) localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // tetap jalan di memori
  }
}

function clear() {
  state.token = null;
  state.user = null;
  state.expiresAt = 0;
  persist();
}

export function authHeaders(): Record<string, string> {
  return state.token ? { Authorization: `Bearer ${state.token}` } : {};
}

/** fetch + header Authorization. 401 = sesi habis: token dibuang supaya UI minta login lagi. */
export async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const headers = { ...(init.headers as Record<string, string> | undefined), ...authHeaders() };
  const res = await fetch(input, { ...init, headers });
  if (res.status === 401 && state.token) clear();
  return res;
}

export function useAuth() {
  const isLoggedIn = computed(() => !!state.token);
  const isAdmin = computed(() => state.user?.role === 'admin');
  const user = computed(() => state.user);

  async function login(username: string, password: string): Promise<void> {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body?.detail || `HTTP ${res.status}`);
    }
    const body = await res.json();
    state.token = body.access_token;
    state.user = body.user;
    state.expiresAt = body.expires_at;
    persist();
  }

  async function logout(): Promise<void> {
    if (state.token) {
      await apiFetch('/api/auth/logout', { method: 'POST' }).catch(() => undefined);
    }
    clear();
  }

  return { isLoggedIn, isAdmin, user, login, logout };
}
