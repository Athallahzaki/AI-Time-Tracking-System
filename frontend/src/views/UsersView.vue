<script setup>
import { computed, onMounted, ref } from 'vue';
import {
  KeyRound,
  MoreHorizontal,
  Power,
  RefreshCw,
  ShieldCheck,
  ShieldPlus,
  UserCog,
} from '@lucide/vue';
import DashboardLayout from '@/layouts/DashboardLayout.vue';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
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
import { nativeSelectClass } from '@/components/common/nativeSelect';
import { createUser, listUsers, resetUserPassword, updateUser } from '@/api/users';
import { useAuth } from '@/composables/useAuth';
import { formatDateTime } from '@/lib/format';

// Manajemen pengguna (akun login) — menu TERPISAH dari data karyawan (dok. 12 §3.2).
// Akun viewer sebaiknya dibuat dari halaman Data Karyawan ("Buat akun").
const { user: me } = useAuth();

const users = ref([]);
const loading = ref(false);
const loadError = ref('');
const roleFilter = ref('all');

const createOpen = ref(false);
const createForm = ref({ username: '', password: '', confirm: '', role: 'admin' });
const createError = ref('');
const creating = ref(false);

const confirmState = ref({ open: false, user: null, action: '', busy: false, error: '' });
const credentials = ref({ open: false, username: '', password: '' });

const activeAdmins = computed(() => users.value.filter((u) => u.role === 'admin' && u.enabled));
const visible = computed(() =>
  users.value
    .filter((u) => roleFilter.value === 'all' || u.role === roleFilter.value)
    .sort((a, b) => (a.role === b.role ? a.username.localeCompare(b.username) : a.role === 'admin' ? -1 : 1)),
);

function isLastAdmin(u) {
  return u.role === 'admin' && u.enabled && activeAdmins.value.length <= 1;
}
function isSelf(u) {
  return me.value && (u.id === me.value.id || u.username === me.value.username);
}

async function load() {
  loading.value = true;
  loadError.value = '';
  try {
    users.value = await listUsers();
  } catch (err) {
    loadError.value = err?.message || 'Gagal memuat pengguna.';
  } finally {
    loading.value = false;
  }
}

onMounted(load);

function openCreate() {
  createForm.value = { username: '', password: '', confirm: '', role: 'admin' };
  createError.value = '';
  createOpen.value = true;
}

async function submitCreate() {
  const f = createForm.value;
  if (!f.username.trim()) return (createError.value = 'Username wajib diisi.');
  if (f.password.length < 8) return (createError.value = 'Password minimal 8 karakter.');
  if (f.password !== f.confirm) return (createError.value = 'Konfirmasi password tidak sama.');
  creating.value = true;
  createError.value = '';
  try {
    const created = await createUser({ username: f.username.trim(), password: f.password, role: f.role });
    users.value.push(created);
    createOpen.value = false;
  } catch (err) {
    createError.value = /exists/i.test(err?.message || '') ? 'Username sudah dipakai.' : err?.message || 'Gagal membuat pengguna.';
  } finally {
    creating.value = false;
  }
}

const confirmText = computed(() => {
  const { user: u, action } = confirmState.value;
  if (!u) return { title: '', description: '', label: '' };
  if (action === 'toggle')
    return u.enabled
      ? { title: `Nonaktifkan ${u.username}?`, description: 'Pengguna tidak bisa login sampai diaktifkan kembali.', label: 'Nonaktifkan' }
      : { title: `Aktifkan ${u.username}?`, description: 'Pengguna bisa login lagi dengan password terakhirnya.', label: 'Aktifkan' };
  if (action === 'role')
    return u.role === 'admin'
      ? { title: `Turunkan ${u.username} menjadi viewer?`, description: 'Viewer hanya melihat notifikasi dan pemakaian miliknya sendiri.', label: 'Jadikan viewer' }
      : { title: `Jadikan ${u.username} admin?`, description: 'Admin (HR) punya akses penuh: monitoring, report, data karyawan, pengguna, dan pengaturan.', label: 'Jadikan admin' };
  return {
    title: `Reset password ${u.username}?`,
    description: 'Password lama langsung tidak berlaku. Password sementara baru wajib diganti saat login.',
    label: 'Reset password',
  };
});

function ask(u, action) {
  confirmState.value = { open: true, user: u, action, busy: false, error: '' };
}

async function runConfirm() {
  const { user: u, action } = confirmState.value;
  confirmState.value.busy = true;
  confirmState.value.error = '';
  try {
    if (action === 'reset') {
      const res = await resetUserPassword(u.id);
      confirmState.value.open = false;
      credentials.value = { open: true, username: u.username, password: res.temporary_password };
      return;
    }
    const patch = action === 'toggle' ? { enabled: !u.enabled } : { role: u.role === 'admin' ? 'viewer' : 'admin' };
    const updated = await updateUser(u.id, patch);
    const idx = users.value.findIndex((x) => x.id === u.id);
    if (idx >= 0) users.value[idx] = { ...users.value[idx], ...updated };
    confirmState.value.open = false;
  } catch (err) {
    confirmState.value.error = err?.message || 'Gagal memproses.';
  } finally {
    confirmState.value.busy = false;
  }
}
</script>

<template>
  <DashboardLayout :crumbs="['Sistem', 'Manajemen Pengguna']">
    <div class="mx-auto max-w-5xl space-y-5">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 class="flex items-center gap-2 text-2xl font-bold tracking-tight text-slate-900">
            <ShieldCheck class="h-6 w-6 text-indigo-600" />
            Manajemen Pengguna
          </h1>
          <p class="mt-1 text-sm text-slate-500">
            Akun login dashboard. Akun karyawan (viewer) dibuat dari halaman
            <RouterLink to="/employees" class="font-medium text-indigo-600 hover:underline">Data Karyawan</RouterLink>.
          </p>
        </div>
        <div class="flex gap-2">
          <Button variant="outline" size="sm" :disabled="loading" @click="load">
            <RefreshCw :class="loading && 'animate-spin'" />
            Muat ulang
          </Button>
          <Button size="sm" class="bg-indigo-600 hover:bg-indigo-700" @click="openCreate">
            <ShieldPlus />
            Tambah admin
          </Button>
        </div>
      </div>

      <DataSourceBanner :domains="['users']" />

      <Card class="gap-0 py-0 shadow-xs">
        <div class="flex items-center justify-between gap-2 border-b p-3">
          <p class="text-xs text-slate-500">
            {{ activeAdmins.length }} admin aktif · {{ users.filter((u) => u.role !== 'admin').length }} akun karyawan
          </p>
          <select v-model="roleFilter" :class="nativeSelectClass" class="w-40" aria-label="Filter peran">
            <option value="all">Semua peran</option>
            <option value="admin">Admin (HR)</option>
            <option value="viewer">Karyawan (viewer)</option>
          </select>
        </div>

        <p v-if="loadError" class="m-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{{ loadError }}</p>

        <div :class="tableClass.wrapper">
          <table :class="tableClass.table">
            <thead :class="tableClass.thead">
              <tr>
                <th :class="tableClass.th">Username</th>
                <th :class="tableClass.th">Peran</th>
                <th :class="tableClass.th" class="hidden sm:table-cell">Karyawan</th>
                <th :class="tableClass.th">Status</th>
                <th :class="tableClass.th" class="hidden md:table-cell">Dibuat</th>
                <th :class="tableClass.th" class="w-10"><span class="sr-only">Aksi</span></th>
              </tr>
            </thead>
            <tbody :class="tableClass.tbody">
              <tr v-if="loading && !users.length">
                <td colspan="6" class="px-3 py-10 text-center text-sm text-slate-400">Memuat pengguna…</td>
              </tr>
              <tr v-for="u in visible" :key="u.id" :class="[tableClass.tr, !u.enabled && 'opacity-60']">
                <td :class="tableClass.td">
                  <span class="font-mono text-sm font-semibold text-slate-900">{{ u.username }}</span>
                  <span v-if="isSelf(u)" class="ml-2 rounded bg-slate-100 px-1.5 text-[10px] text-slate-500">Anda</span>
                  <span v-if="u.must_change_password" class="ml-2 rounded bg-amber-50 px-1.5 text-[10px] text-amber-700">wajib ganti password</span>
                </td>
                <td :class="tableClass.td">
                  <span
                    class="rounded-full px-2 py-0.5 text-[11px] font-semibold"
                    :class="u.role === 'admin' ? 'bg-indigo-50 text-indigo-700' : 'bg-slate-100 text-slate-600'"
                  >{{ u.role === 'admin' ? 'Admin (HR)' : 'Karyawan' }}</span>
                </td>
                <td :class="tableClass.td" class="hidden text-xs text-slate-600 sm:table-cell">
                  {{ u.employee_id || (u.role === 'admin' ? '—' : u.username) }}
                </td>
                <td :class="tableClass.td">
                  <span
                    class="rounded-full px-2 py-0.5 text-[11px] font-semibold"
                    :class="u.enabled ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'"
                  >{{ u.enabled ? 'Aktif' : 'Nonaktif' }}</span>
                </td>
                <td :class="tableClass.td" class="hidden text-xs text-slate-500 md:table-cell">{{ formatDateTime(u.created_at) }}</td>
                <td :class="tableClass.td" class="text-right">
                  <DropdownMenu>
                    <DropdownMenuTrigger as-child>
                      <Button variant="ghost" size="icon-sm" :aria-label="`Aksi untuk ${u.username}`">
                        <MoreHorizontal />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" class="w-60">
                      <DropdownMenuItem :disabled="isSelf(u) || isLastAdmin(u)" @select="ask(u, 'role')">
                        <UserCog />
                        {{ u.role === 'admin' ? 'Jadikan viewer' : 'Jadikan admin' }}
                      </DropdownMenuItem>
                      <DropdownMenuItem @select="ask(u, 'reset')">
                        <KeyRound />
                        Reset password
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        :variant="u.enabled ? 'destructive' : 'default'"
                        :disabled="isSelf(u) || isLastAdmin(u)"
                        @select="ask(u, 'toggle')"
                      >
                        <Power />
                        {{ u.enabled ? 'Nonaktifkan' : 'Aktifkan' }}
                      </DropdownMenuItem>
                      <p
                        v-if="isLastAdmin(u) || isSelf(u)"
                        class="px-2 pt-1.5 pb-1 text-[11px] leading-snug text-slate-400"
                      >
                        {{ isLastAdmin(u) ? 'Admin terakhir tidak boleh dinonaktifkan atau diturunkan.' : 'Anda tidak bisa menonaktifkan/menurunkan akun sendiri.' }}
                      </p>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>
    </div>

    <Dialog v-model:open="createOpen">
      <DialogContent class="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Tambah pengguna</DialogTitle>
          <DialogDescription>
            Untuk akun HR/admin. Akun karyawan lebih baik dibuat dari Data Karyawan supaya terhubung ke datanya.
          </DialogDescription>
        </DialogHeader>
        <form id="create-user-form" class="space-y-3" @submit.prevent="submitCreate">
          <div class="space-y-1.5">
            <Label for="new-username" class="text-xs font-semibold text-slate-700">Username</Label>
            <Input id="new-username" v-model="createForm.username" autocomplete="off" />
          </div>
          <div class="space-y-1.5">
            <Label for="new-role" class="text-xs font-semibold text-slate-700">Peran</Label>
            <select id="new-role" v-model="createForm.role" :class="nativeSelectClass">
              <option value="admin">Admin (HR)</option>
              <option value="viewer">Karyawan (viewer)</option>
            </select>
          </div>
          <div class="grid gap-3 sm:grid-cols-2">
            <div class="space-y-1.5">
              <Label for="new-password" class="text-xs font-semibold text-slate-700">Password</Label>
              <Input id="new-password" v-model="createForm.password" type="password" autocomplete="new-password" />
            </div>
            <div class="space-y-1.5">
              <Label for="new-confirm" class="text-xs font-semibold text-slate-700">Ulangi password</Label>
              <Input id="new-confirm" v-model="createForm.confirm" type="password" autocomplete="new-password" />
            </div>
          </div>
          <p class="text-[11px] text-slate-400">Minimal 8 karakter.</p>
          <p v-if="createError" class="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{{ createError }}</p>
        </form>
        <DialogFooter>
          <Button variant="outline" :disabled="creating" @click="createOpen = false">Batal</Button>
          <Button type="submit" form="create-user-form" :disabled="creating">{{ creating ? 'Menyimpan…' : 'Buat pengguna' }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <ConfirmDialog
      v-model:open="confirmState.open"
      :title="confirmText.title"
      :description="confirmText.description"
      :confirm-label="confirmText.label"
      :destructive="confirmState.action === 'toggle' && !!confirmState.user?.enabled"
      :busy="confirmState.busy"
      :error="confirmState.error"
      @confirm="runConfirm"
    />

    <CredentialsDialog
      v-model:open="credentials.open"
      title="Password direset"
      :username="credentials.username"
      :password="credentials.password"
    />
  </DashboardLayout>
</template>
