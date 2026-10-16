<script setup>
import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';
import { AlertCircle, CheckCircle2, KeyRound, LogOut } from '@lucide/vue';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { changeOwnPassword } from '@/api/users';
import { homePathFor, useAuth } from '@/composables/useAuth';

// Halaman ganti password. Dipaksa saat login pertama dengan password sementara
// (must_change_password dari /api/auth/me), dan bisa dibuka dari menu akun.
const router = useRouter();
const { user, mustChangePassword, markPasswordChanged, logout } = useAuth();

const oldPassword = ref('');
const newPassword = ref('');
const confirm = ref('');
const error = ref('');
const done = ref(false);
const saving = ref(false);

const rules = computed(() => [
  { ok: newPassword.value.length >= 8, text: 'Minimal 8 karakter' },
  { ok: !!newPassword.value && newPassword.value !== oldPassword.value, text: 'Berbeda dari password lama' },
  { ok: !!newPassword.value && newPassword.value === confirm.value, text: 'Konfirmasi sama' },
]);
const valid = computed(() => !!oldPassword.value && rules.value.every((r) => r.ok));

async function submit() {
  if (!valid.value) return;
  saving.value = true;
  error.value = '';
  try {
    await changeOwnPassword(oldPassword.value, newPassword.value);
    markPasswordChanged();
    done.value = true;
    setTimeout(() => router.replace(homePathFor(user.value)), 1200);
  } catch (err) {
    error.value = err?.message || 'Gagal mengganti password.';
  } finally {
    saving.value = false;
  }
}

async function handleLogout() {
  await logout();
  router.replace('/login');
}
</script>

<template>
  <div class="flex min-h-svh flex-col items-center justify-center bg-slate-50 px-4 py-10">
    <Card class="w-full max-w-sm shadow-xs">
      <CardHeader>
        <div class="mb-1 flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
          <KeyRound class="h-5 w-5" />
        </div>
        <CardTitle>{{ mustChangePassword ? 'Ganti password sementara' : 'Ganti password' }}</CardTitle>
        <CardDescription>
          <template v-if="mustChangePassword">
            Akun <b>{{ user?.username }}</b> masih memakai password sementara dari HR. Ganti dulu sebelum melanjutkan.
          </template>
          <template v-else>Akun {{ user?.username }}</template>
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div v-if="done" class="flex items-center gap-2 rounded-md bg-emerald-50 px-3 py-3 text-sm text-emerald-800">
          <CheckCircle2 class="h-4 w-4" />
          Password diganti. Mengalihkan…
        </div>
        <form v-else class="space-y-3" @submit.prevent="submit">
          <div class="space-y-1.5">
            <Label for="old-pw" class="text-xs font-semibold text-slate-700">Password saat ini</Label>
            <Input id="old-pw" v-model="oldPassword" type="password" autocomplete="current-password" />
          </div>
          <div class="space-y-1.5">
            <Label for="new-pw" class="text-xs font-semibold text-slate-700">Password baru</Label>
            <Input id="new-pw" v-model="newPassword" type="password" autocomplete="new-password" />
          </div>
          <div class="space-y-1.5">
            <Label for="confirm-pw" class="text-xs font-semibold text-slate-700">Ulangi password baru</Label>
            <Input id="confirm-pw" v-model="confirm" type="password" autocomplete="new-password" />
          </div>
          <ul class="space-y-0.5 text-[11px]">
            <li v-for="r in rules" :key="r.text" :class="r.ok ? 'text-emerald-700' : 'text-slate-400'">
              {{ r.ok ? '✓' : '•' }} {{ r.text }}
            </li>
          </ul>
          <div v-if="error" class="flex items-start gap-2 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">
            <AlertCircle class="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {{ error }}
          </div>
          <Button type="submit" class="w-full" :disabled="!valid || saving">
            {{ saving ? 'Menyimpan…' : 'Simpan password baru' }}
          </Button>
          <div class="flex justify-between pt-1">
            <button
              v-if="!mustChangePassword"
              type="button"
              class="text-xs text-slate-500 hover:text-slate-800"
              @click="router.back()"
            >
              Kembali
            </button>
            <span v-else />
            <button type="button" class="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-red-600" @click="handleLogout">
              <LogOut class="h-3.5 w-3.5" />
              Keluar
            </button>
          </div>
        </form>
      </CardContent>
    </Card>
  </div>
</template>
