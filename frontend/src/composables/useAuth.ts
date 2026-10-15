import { computed, reactive } from 'vue';

// Login minimal (workplan demo D7). Backend: /api/auth/login mengembalikan
// token bearer; endpoint yang mengubah data (enrollment, koreksi, kamera,
// pengaturan) butuh peran admin. Token disimpan di localStorage supaya tidak
// hilang saat halaman di-refresh; berakhir sendiri setelah AUTH_SESSION_HOURS.

export interface AuthUser {
  id: number;
  username: string;
  role: 'admin' | 'viewer' | string;
  /** Field berikut diharapkan dari /api/auth/me versi baru (dok. 12 §3.2). */
  employee_uid?: string | null;
  employee_id?: string | null;
  name?: string | null;
  must_change_password?: boolean;
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

/** Username pengguna aktif (untuk jejak audit di mode simulasi). */
export function currentUsername(): string {
  return state.user?.username || 'tidak diketahui';
}

/**
 * ID karyawan milik akun viewer. Selama /api/auth/me belum mengirim
 * employee_id, dipakai username — akun viewer dibuat dengan username = ID
 * karyawan (dok. 12 §3.2).
 */
export function employeeIdOf(user: AuthUser | null): string | null {
  if (!user) return null;
  return user.employee_id || user.username || null;
}

export function homePathFor(user: AuthUser | null): string {
  return user?.role === 'admin' ? '/' : '/me';
}

export function useAuth() {
  const isLoggedIn = computed(() => !!state.token);
  const isAdmin = computed(() => state.user?.role === 'admin');
  const isViewer = computed(() => !!state.user && state.user.role !== 'admin');
  const mustChangePassword = computed(() => !!state.user?.must_change_password);
  const user = computed(() => state.user);

  /** Ambil ulang profil dari /api/auth/me supaya field baru (bila BE sudah punya) ikut terbaca. */
  async function refreshMe(): Promise<void> {
    if (!state.token) return;
    try {
      const res = await apiFetch('/api/auth/me');
      if (!res.ok) return;
      const body = await res.json();
      if (body?.user && state.user) {
        state.user = { ...state.user, ...body.user };
        persist();
      }
    } catch {
      // jaringan putus: pakai data login yang tersimpan
    }
  }

  function markPasswordChanged(): void {
    if (state.user) {
      state.user = { ...state.user, must_change_password: false };
      persist();
    }
  }

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
    await refreshMe();
  }

  async function logout(): Promise<void> {
    if (state.token) {
      await apiFetch('/api/auth/logout', { method: 'POST' }).catch(() => undefined);
    }
    clear();
  }

  return {
    isLoggedIn,
    isAdmin,
    isViewer,
    mustChangePassword,
    user,
    login,
    logout,
    refreshMe,
    markPasswordChanged,
  };
}
