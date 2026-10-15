<script setup>
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { refDebounced } from '@vueuse/core';
import {
  Camera,
  KeyRound,
  MailWarning,
  MoreHorizontal,
  Pencil,
  Power,
  RefreshCw,
  Search,
  UserPlus,
  Users,
} from '@lucide/vue';
import DashboardLayout from '@/layouts/DashboardLayout.vue';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { tableClass } from '@/components/ui/table';
import DataSourceBanner from '@/components/common/DataSourceBanner.vue';
import ConfirmDialog from '@/components/common/ConfirmDialog.vue';
import CredentialsDialog from '@/components/common/CredentialsDialog.vue';
import EmployeeFormDialog from '@/components/employees/EmployeeFormDialog.vue';
import { nativeSelectClass } from '@/components/common/nativeSelect';
import { createEmployeeAccount, listEmployees, setEmployeeActive } from '@/api/employees';
import { apiSources } from '@/api/http';

const router = useRouter();

const employees = ref([]);
const loading = ref(false);
const loadError = ref('');

const search = ref('');
const debouncedSearch = refDebounced(search, 200);
const statusFilter = ref('active');
const divisionFilter = ref('');

const formOpen = ref(false);
const editing = ref(null);

const confirmState = ref({ open: false, employee: null, busy: false, error: '' });
const accountConfirm = ref({ open: false, employee: null, busy: false, error: '' });
const credentials = ref({ open: false, username: '', password: '', note: '' });

const divisions = computed(() =>
  [...new Set(employees.value.map((e) => e.division).filter(Boolean))].sort(),
);

const visible = computed(() => {
  const q = debouncedSearch.value.trim().toLowerCase();
  return employees.value
    .filter((e) => {
      if (statusFilter.value === 'active' && !e.active) return false;
      if (statusFilter.value === 'inactive' && e.active) return false;
      if (divisionFilter.value && e.division !== divisionFilter.value) return false;
      if (!q) return true;
      return `${e.employee_id} ${e.name} ${e.division || ''} ${e.email || ''}`.toLowerCase().includes(q);
    })
    .sort((a, b) => a.employee_id.localeCompare(b.employee_id));
});

const counts = computed(() => ({
  total: employees.value.length,
  active: employees.value.filter((e) => e.active).length,
  enrolled: employees.value.filter((e) => e.active && e.enrolled_refs > 0).length,
  noEmail: employees.value.filter((e) => e.active && !e.email).length,
  withAccount: employees.value.filter((e) => e.active && e.has_account).length,
}));

async function load() {
  loading.value = true;
  loadError.value = '';
  try {
    // Ambil semua status; penyaringan dilakukan di layar supaya ganti filter instan.
    employees.value = await listEmployees({ status: 'all' });
  } catch (err) {
    loadError.value = err?.message || 'Gagal memuat data karyawan.';
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function openCreate() {
  editing.value = null;
  formOpen.value = true;
}

function openEdit(employee) {
  editing.value = employee;
  formOpen.value = true;
}

function onSaved(saved) {
  const idx = employees.value.findIndex((e) => e.uid === saved.uid);
  if (idx >= 0) employees.value[idx] = saved;
  else employees.value.push(saved);
}

function askToggleActive(employee) {
  confirmState.value = { open: true, employee, busy: false, error: '' };
}

async function confirmToggleActive() {
  const target = confirmState.value.employee;
  confirmState.value.busy = true;
  confirmState.value.error = '';
  try {
    onSaved(await setEmployeeActive(target.uid, !target.active));
    confirmState.value.open = false;
  } catch (err) {
    confirmState.value.error = err?.message || 'Gagal mengubah status karyawan.';
  } finally {
    confirmState.value.busy = false;
  }
}

function askCreateAccount(employee) {
  accountConfirm.value = { open: true, employee, busy: false, error: '' };
}

async function confirmCreateAccount() {
  const employee = accountConfirm.value.employee;
  accountConfirm.value.busy = true;
  accountConfirm.value.error = '';
  try {
    const creds = await createEmployeeAccount(employee);
    accountConfirm.value.open = false;
    onSaved({ ...employee, has_account: true });
    credentials.value = {
      open: true,
      username: creds.username,
      password: creds.temporary_password,
      note:
        apiSources.employees === 'mock'
          ? 'Endpoint akun karyawan belum ada di BE; akun dibuat lewat /api/auth/users (peran viewer). Kewajiban ganti password saat login pertama baru berlaku setelah BE mendukungnya.'
          : '',
    };
  } catch (err) {
    accountConfirm.value.error =
      err?.status === 409 || /exists|dipakai/i.test(err?.message || '')
        ? `Username ${employee.employee_id} sudah dipakai akun lain.`
        : err?.message || 'Gagal membuat akun.';
  } finally {
    accountConfirm.value.busy = false;
  }
}

function goEnroll(employee) {
  router.push({ path: '/enrollment', query: { employee: employee.uid } });
}
</script>

<template>
  <DashboardLayout :crumbs="['Karyawan', 'Data Karyawan']">
    <div class="mx-auto max-w-7xl space-y-5">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 class="flex items-center gap-2 text-2xl font-bold tracking-tight text-slate-900">
            <Users class="h-6 w-6 text-indigo-600" />
            Data Karyawan
          </h1>
          <p class="mt-1 text-sm text-slate-500">
            Data master untuk enrollment wajah, akun karyawan, dan tujuan email pelanggaran.
          </p>
        </div>
        <div class="flex gap-2">
          <Button variant="outline" size="sm" :disabled="loading" @click="load">
            <RefreshCw :class="loading && 'animate-spin'" />
            Muat ulang
          </Button>
          <Button size="sm" class="bg-indigo-600 hover:bg-indigo-700" @click="openCreate">
            <UserPlus />
            Tambah karyawan
          </Button>
        </div>
      </div>

      <DataSourceBanner :domains="['employees', 'users']" />

      <div class="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div class="rounded-xl border bg-white px-4 py-3">
          <p class="text-xs text-slate-500">Karyawan aktif</p>
          <p class="mt-1 text-2xl font-semibold text-slate-900">{{ counts.active }}<span class="text-sm font-normal text-slate-400"> / {{ counts.total }}</span></p>
        </div>
        <div class="rounded-xl border bg-white px-4 py-3">
          <p class="text-xs text-slate-500">Wajah terdaftar</p>
          <p class="mt-1 text-2xl font-semibold text-slate-900">{{ counts.enrolled }}</p>
        </div>
        <div class="rounded-xl border bg-white px-4 py-3">
          <p class="text-xs text-slate-500">Punya akun</p>
          <p class="mt-1 text-2xl font-semibold text-slate-900">{{ counts.withAccount }}</p>
        </div>
        <div class="rounded-xl border bg-white px-4 py-3">
          <p class="text-xs text-slate-500">Tanpa email</p>
          <p class="mt-1 text-2xl font-semibold" :class="counts.noEmail ? 'text-amber-600' : 'text-slate-900'">{{ counts.noEmail }}</p>
        </div>
      </div>

      <Card class="gap-0 py-0 shadow-xs">
        <div class="flex flex-col gap-2 border-b p-3 sm:flex-row sm:items-center">
          <div class="relative flex-1">
            <Search class="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <Input v-model="search" class="pl-9" placeholder="Cari ID, nama, divisi, atau email…" aria-label="Cari karyawan" />
          </div>
          <select v-model="statusFilter" :class="nativeSelectClass" class="sm:w-40" aria-label="Filter status">
            <option value="active">Aktif</option>
            <option value="inactive">Nonaktif</option>
            <option value="all">Semua status</option>
          </select>
          <select v-model="divisionFilter" :class="nativeSelectClass" class="sm:w-44" aria-label="Filter divisi">
            <option value="">Semua divisi</option>
            <option v-for="d in divisions" :key="d" :value="d">{{ d }}</option>
          </select>
        </div>

        <p v-if="loadError" class="m-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{{ loadError }}</p>

        <div :class="tableClass.wrapper">
          <table :class="tableClass.table">
            <thead :class="tableClass.thead">
              <tr>
                <th :class="tableClass.th">ID</th>
                <th :class="tableClass.th">Nama</th>
                <th :class="tableClass.th" class="hidden md:table-cell">Divisi</th>
                <th :class="tableClass.th" class="hidden lg:table-cell">Email</th>
                <th :class="tableClass.th">Wajah</th>
                <th :class="tableClass.th" class="hidden sm:table-cell">Akun</th>
                <th :class="tableClass.th">Status</th>
                <th :class="tableClass.th" class="w-10"><span class="sr-only">Aksi</span></th>
              </tr>
            </thead>
            <tbody :class="tableClass.tbody">
              <tr v-if="loading && !employees.length">
                <td colspan="8" class="px-3 py-10 text-center text-sm text-slate-400">Memuat data karyawan…</td>
              </tr>
              <tr v-else-if="!visible.length">
                <td colspan="8" class="px-3 py-10 text-center text-sm text-slate-400">
                  <template v-if="!employees.length">
                    Belum ada data karyawan.
                    <button class="font-medium text-indigo-600 hover:underline" @click="openCreate">Tambah karyawan pertama</button>
                  </template>
                  <template v-else>Tidak ada karyawan yang cocok dengan filter.</template>
                </td>
              </tr>
              <tr
                v-for="e in visible"
                :key="e.uid"
                :class="[tableClass.tr, !e.active && 'opacity-60']"
              >
                <td :class="tableClass.td" class="font-mono text-xs font-semibold text-slate-800">{{ e.employee_id }}</td>
                <td :class="tableClass.td">
                  <p class="font-medium text-slate-900">{{ e.name }}</p>
                  <p class="text-xs text-slate-400 md:hidden">{{ e.division || '—' }}</p>
                </td>
                <td :class="tableClass.td" class="hidden text-slate-600 md:table-cell">{{ e.division || '—' }}</td>
                <td :class="tableClass.td" class="hidden lg:table-cell">
                  <span v-if="e.email" class="text-slate-600">{{ e.email }}</span>
                  <span
                    v-else
                    class="inline-flex items-center gap-1 text-xs text-amber-700"
                    title="Email pelanggaran akan dikirim ke HR saja"
                  >
                    <MailWarning class="h-3.5 w-3.5" />
                    tanpa email → HR
                  </span>
                </td>
                <td :class="tableClass.td">
                  <span
                    v-if="e.enrolled_refs > 0"
                    class="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700"
                  >{{ e.enrolled_refs }} foto</span>
                  <span v-else class="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500">belum</span>
                </td>
                <td :class="tableClass.td" class="hidden sm:table-cell">
                  <span v-if="e.has_account" class="text-xs font-medium text-indigo-700">Ada</span>
                  <span v-else class="text-xs text-slate-400">—</span>
                </td>
                <td :class="tableClass.td">
                  <span
                    class="rounded-full px-2 py-0.5 text-[11px] font-semibold"
                    :class="e.active ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'"
                  >{{ e.active ? 'Aktif' : 'Nonaktif' }}</span>
                </td>
                <td :class="tableClass.td" class="text-right">
                  <DropdownMenu>
                    <DropdownMenuTrigger as-child>
                      <Button variant="ghost" size="icon-sm" :aria-label="`Aksi untuk ${e.name}`">
                        <MoreHorizontal />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" class="w-52">
                      <DropdownMenuItem @select="openEdit(e)">
                        <Pencil />
                        Ubah data
                      </DropdownMenuItem>
                      <DropdownMenuItem :disabled="!e.active" @select="goEnroll(e)">
                        <Camera />
                        {{ e.enrolled_refs > 0 ? 'Perbarui wajah' : 'Daftarkan wajah' }}
                      </DropdownMenuItem>
                      <DropdownMenuItem :disabled="!e.active || e.has_account" @select="askCreateAccount(e)">
                        <KeyRound />
                        {{ e.has_account ? 'Akun sudah ada' : 'Buat akun' }}
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem :variant="e.active ? 'destructive' : 'default'" @select="askToggleActive(e)">
                        <Power />
                        {{ e.active ? 'Nonaktifkan' : 'Aktifkan kembali' }}
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="border-t px-4 py-2.5 text-xs text-slate-400">
          Menampilkan {{ visible.length }} dari {{ employees.length }} karyawan
        </div>
      </Card>
    </div>

    <EmployeeFormDialog
      v-model:open="formOpen"
      :employee="editing"
      :divisions="divisions"
      @saved="onSaved"
    />

    <ConfirmDialog
      v-model:open="confirmState.open"
      :title="confirmState.employee?.active ? `Nonaktifkan ${confirmState.employee?.name}?` : `Aktifkan kembali ${confirmState.employee?.name}?`"
      :confirm-label="confirmState.employee?.active ? 'Nonaktifkan' : 'Aktifkan'"
      :destructive="!!confirmState.employee?.active"
      :busy="confirmState.busy"
      :error="confirmState.error"
      @confirm="confirmToggleActive"
    >
      <div v-if="confirmState.employee?.active" class="space-y-2 text-sm text-slate-600">
        <p>Yang terjadi:</p>
        <ul class="list-disc space-y-1 pl-5">
          <li><b>Referensi wajah dihapus</b> dari engine (UU PDP). Bila diaktifkan lagi, wajah harus didaftarkan ulang.</li>
          <li>Akun login karyawan ini ikut dinonaktifkan.</li>
          <li>Riwayat pemakaian dan report lama tetap tersimpan.</li>
        </ul>
      </div>
      <p v-else class="text-sm text-slate-600">
        Karyawan akan muncul lagi di pilihan enrollment. Referensi wajah lama sudah dihapus, jadi daftarkan wajah ulang.
      </p>
    </ConfirmDialog>

    <ConfirmDialog
      v-model:open="accountConfirm.open"
      :title="`Buat akun untuk ${accountConfirm.employee?.name}?`"
      confirm-label="Buat akun"
      :busy="accountConfirm.busy"
      :error="accountConfirm.error"
      @confirm="confirmCreateAccount"
    >
      <p class="text-sm text-slate-600">
        Username: <b class="font-mono">{{ accountConfirm.employee?.employee_id }}</b>. Password sementara dibuat
        otomatis. Akun karyawan hanya bisa melihat notifikasi dan pemakaian free time miliknya sendiri.
      </p>
    </ConfirmDialog>

    <CredentialsDialog
      v-model:open="credentials.open"
      title="Akun karyawan dibuat"
      :username="credentials.username"
      :password="credentials.password"
      :note="credentials.note"
    />
  </DashboardLayout>
</template>
