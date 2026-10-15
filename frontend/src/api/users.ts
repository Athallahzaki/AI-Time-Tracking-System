import { ApiError, request } from './http';
import { clone, db, generateTempPassword, save } from './mock/db';
import type { AppUser } from './types';

// GET/POST /api/auth/users SUDAH ADA di backend. PATCH dan reset-password belum:
// kalau daftar pengguna berasal dari backend, aksi itu akan menampilkan error
// "endpoint belum tersedia" (bukan diam-diam mengubah data palsu).
const DOMAIN = 'users';

export interface CreateUserInput {
  username: string;
  password: string;
  role: 'admin' | 'viewer';
  employee_id?: string | null;
  must_change_password?: boolean;
}

function activeAdmins(users: AppUser[]): AppUser[] {
  return users.filter((u) => u.role === 'admin' && u.enabled);
}

function findOr404(id: number): AppUser {
  const user = db().users.find((u) => u.id === id);
  if (!user) throw new ApiError('Pengguna tidak ditemukan.', 404);
  return user;
}

export async function listUsers(): Promise<AppUser[]> {
  const res = await request<{ users: AppUser[] }>({
    domain: DOMAIN,
    path: '/api/auth/users',
    mock: () => ({ users: clone(db().users) }),
  });
  return res.users || [];
}

export async function createUser(input: CreateUserInput): Promise<AppUser> {
  const res = await request<{ user: AppUser }>({
    domain: DOMAIN,
    method: 'POST',
    path: '/api/auth/users',
    body: input,
    mock: () => {
      const store = db();
      if (input.password.length < 8) throw new ApiError('Password minimal 8 karakter.', 422);
      if (store.users.some((u) => u.username.toLowerCase() === input.username.toLowerCase())) {
        throw new ApiError('Username sudah dipakai.', 409);
      }
      const user: AppUser = {
        id: store.nextUserId++,
        username: input.username,
        role: input.role,
        enabled: true,
        created_at: Date.now() / 1000,
        employee_id: input.employee_id ?? null,
        must_change_password: input.must_change_password ?? false,
      };
      store.users.push(user);
      save();
      return { user: clone(user) };
    },
  });
  return res.user;
}

export async function updateUser(
  id: number,
  patch: { role?: 'admin' | 'viewer'; enabled?: boolean },
): Promise<AppUser> {
  const res = await request<{ user: AppUser }>({
    domain: DOMAIN,
    method: 'PATCH',
    path: `/api/auth/users/${id}`,
    body: patch,
    mock: () => {
      const store = db();
      const user = findOr404(id);
      const losingAdmin =
        user.role === 'admin' &&
        user.enabled &&
        (patch.enabled === false || (patch.role && patch.role !== 'admin'));
      if (losingAdmin && activeAdmins(store.users).length <= 1) {
        throw new ApiError('Admin terakhir tidak boleh dinonaktifkan atau diturunkan perannya.', 409);
      }
      if (patch.role) user.role = patch.role;
      if (patch.enabled !== undefined) user.enabled = patch.enabled;
      save();
      return { user: clone(user) };
    },
  });
  return res.user;
}

export async function resetUserPassword(id: number): Promise<{ temporary_password: string }> {
  return request({
    domain: DOMAIN,
    method: 'POST',
    path: `/api/auth/users/${id}/reset-password`,
    mock: () => {
      const user = findOr404(id);
      user.must_change_password = true;
      save();
      return { temporary_password: generateTempPassword() };
    },
  });
}

export async function changeOwnPassword(oldPassword: string, newPassword: string): Promise<void> {
  await request({
    domain: 'auth-password',
    method: 'POST',
    path: '/api/auth/change-password',
    body: { old_password: oldPassword, new_password: newPassword },
    // Sengaja tanpa mock: berpura-pura berhasil mengganti password itu menyesatkan.
  });
}
