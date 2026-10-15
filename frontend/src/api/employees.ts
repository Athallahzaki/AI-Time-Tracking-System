import { ApiError, qs, request } from './http';
import { clone, db, generateTempPassword, save, uuid } from './mock/db';
import { createUser } from './users';
import type { AccountCredentials, Employee, EmployeeInput } from './types';

const DOMAIN = 'employees';

export interface EmployeeQuery {
  q?: string;
  status?: 'active' | 'inactive' | 'all';
  division?: string;
}

function normalizeId(value: string): string {
  return value.trim();
}

function matches(e: Employee, query: EmployeeQuery): boolean {
  const status = query.status || 'all';
  if (status === 'active' && !e.active) return false;
  if (status === 'inactive' && e.active) return false;
  if (query.division && e.division !== query.division) return false;
  if (query.q) {
    const q = query.q.toLowerCase();
    const hay = `${e.employee_id} ${e.name} ${e.division || ''} ${e.email || ''}`.toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

function assertUniqueId(employeeId: string, exceptUid?: string) {
  const clash = db().employees.find(
    (e) => e.employee_id.toLowerCase() === employeeId.toLowerCase() && e.uid !== exceptUid,
  );
  if (clash) throw new ApiError(`ID karyawan "${employeeId}" sudah dipakai ${clash.name}.`, 409);
}

function findOr404(uid: string): Employee {
  const found = db().employees.find((e) => e.uid === uid);
  if (!found) throw new ApiError('Karyawan tidak ditemukan.', 404);
  return found;
}

export async function listEmployees(query: EmployeeQuery = {}): Promise<Employee[]> {
  const res = await request<{ items: Employee[] }>({
    domain: DOMAIN,
    path: `/api/employees${qs({ q: query.q, status: query.status, division: query.division })}`,
    mock: () => ({
      items: clone(db().employees.filter((e) => matches(e, query))).sort((a, b) =>
        a.employee_id.localeCompare(b.employee_id),
      ),
    }),
  });
  return res.items || [];
}

export async function createEmployee(input: EmployeeInput): Promise<Employee> {
  const res = await request<{ employee: Employee }>({
    domain: DOMAIN,
    method: 'POST',
    path: '/api/employees',
    body: input,
    mock: () => {
      const employeeId = normalizeId(input.employee_id);
      assertUniqueId(employeeId);
      const employee: Employee = {
        uid: uuid(),
        employee_id: employeeId,
        name: input.name.trim(),
        division: input.division?.trim() || null,
        email: input.email?.trim() || null,
        active: true,
        enrolled_refs: 0,
        has_account: false,
        created_at: Date.now() / 1000,
      };
      db().employees.push(employee);
      save();
      return { employee: clone(employee) };
    },
  });
  return res.employee;
}

export async function updateEmployee(uid: string, input: Partial<EmployeeInput>): Promise<Employee> {
  const res = await request<{ employee: Employee }>({
    domain: DOMAIN,
    method: 'PATCH',
    path: `/api/employees/${encodeURIComponent(uid)}`,
    body: input,
    mock: () => {
      const e = findOr404(uid);
      if (input.employee_id !== undefined) {
        const employeeId = normalizeId(input.employee_id);
        assertUniqueId(employeeId, uid);
        e.employee_id = employeeId;
      }
      if (input.name !== undefined) e.name = input.name.trim();
      if (input.division !== undefined) e.division = input.division?.trim() || null;
      if (input.email !== undefined) e.email = input.email?.trim() || null;
      save();
      return { employee: clone(e) };
    },
  });
  return res.employee;
}

export async function setEmployeeActive(uid: string, active: boolean): Promise<Employee> {
  const res = await request<{ employee: Employee }>({
    domain: DOMAIN,
    method: 'POST',
    path: `/api/employees/${encodeURIComponent(uid)}/${active ? 'activate' : 'deactivate'}`,
    mock: () => {
      const e = findOr404(uid);
      e.active = active;
      if (!active) {
        // Dok. 12 §3.1: nonaktif → referensi wajah dihapus, akun ikut nonaktif.
        e.enrolled_refs = 0;
        for (const u of db().users) {
          if (u.employee_id === e.employee_id) u.enabled = false;
        }
      }
      save();
      return { employee: clone(e) };
    },
  });
  return res.employee;
}

/**
 * "Buat akun" untuk karyawan (dok. 12 §3.2): username = ID karyawan, password
 * sementara, wajib ganti saat login pertama.
 *
 * Bila BE belum punya POST /api/employees/{uid}/account, akun tetap dibuat lewat
 * POST /api/auth/users yang SUDAH ADA (peran viewer), dengan password sementara
 * dibuat di browser. Catatan: endpoint lama belum mengenal flag wajib-ganti-password.
 */
export async function createEmployeeAccount(employee: Employee): Promise<AccountCredentials> {
  return request<AccountCredentials>({
    domain: DOMAIN,
    method: 'POST',
    path: `/api/employees/${encodeURIComponent(employee.uid)}/account`,
    mock: async () => {
      const password = generateTempPassword();
      await createUser({
        username: employee.employee_id,
        password,
        role: 'viewer',
        employee_id: employee.employee_id,
        must_change_password: true,
      });
      const e = db().employees.find((x) => x.uid === employee.uid);
      if (e) {
        e.has_account = true;
        save();
      }
      return { username: employee.employee_id, temporary_password: password };
    },
  });
}

export async function listDivisions(): Promise<string[]> {
  const all = await listEmployees({ status: 'all' });
  return [...new Set(all.map((e) => e.division).filter((d): d is string => !!d))].sort();
}
