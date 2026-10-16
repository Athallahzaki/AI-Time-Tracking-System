<script setup>
import { ref } from 'vue';
import { Check, Copy, KeyRound } from '@lucide/vue';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

// Menampilkan password sementara SEKALI. Setelah ditutup tidak bisa dilihat lagi;
// kalau hilang, admin melakukan reset password.
const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: 'Akun dibuat' },
  username: { type: String, default: '' },
  password: { type: String, default: '' },
  note: { type: String, default: '' },
});

const emit = defineEmits(['update:open']);
const copied = ref('');

async function copy(kind) {
  const text =
    kind === 'all'
      ? `Username: ${props.username}\nPassword sementara: ${props.password}`
      : kind === 'username'
        ? props.username
        : props.password;
  try {
    await navigator.clipboard.writeText(text);
    copied.value = kind;
    setTimeout(() => (copied.value = ''), 1500);
  } catch {
    copied.value = '';
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="(v) => emit('update:open', v)">
    <DialogContent class="sm:max-w-md">
      <DialogHeader>
        <DialogTitle class="flex items-center gap-2">
          <KeyRound class="h-5 w-5 text-indigo-600" />
          {{ title }}
        </DialogTitle>
        <DialogDescription>
          Berikan kredensial ini ke karyawan. Password hanya ditampilkan sekali dan wajib
          diganti saat login pertama.
        </DialogDescription>
      </DialogHeader>

      <div class="space-y-2 rounded-lg border bg-slate-50 p-3">
        <div class="flex items-center justify-between gap-2">
          <div class="min-w-0">
            <p class="text-[11px] text-slate-500">Username</p>
            <p class="truncate font-mono text-sm font-semibold text-slate-900">{{ username }}</p>
          </div>
          <Button variant="ghost" size="icon-sm" aria-label="Salin username" @click="copy('username')">
            <Check v-if="copied === 'username'" class="text-emerald-600" />
            <Copy v-else />
          </Button>
        </div>
        <div class="flex items-center justify-between gap-2">
          <div class="min-w-0">
            <p class="text-[11px] text-slate-500">Password sementara</p>
            <p class="truncate font-mono text-sm font-semibold tracking-wider text-slate-900">{{ password }}</p>
          </div>
          <Button variant="ghost" size="icon-sm" aria-label="Salin password" @click="copy('password')">
            <Check v-if="copied === 'password'" class="text-emerald-600" />
            <Copy v-else />
          </Button>
        </div>
      </div>

      <p v-if="note" class="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800">{{ note }}</p>

      <DialogFooter>
        <Button variant="outline" @click="copy('all')">
          <Check v-if="copied === 'all'" class="text-emerald-600" />
          <Copy v-else />
          Salin keduanya
        </Button>
        <Button @click="emit('update:open', false)">Selesai</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
