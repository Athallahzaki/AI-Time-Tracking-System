<script setup>
import { computed, onMounted, ref } from 'vue';
import { AlertCircle, CheckCircle2, Mail, Plus, RotateCcw, Save, Send, Server, X } from '@lucide/vue';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { getEmailConfig, saveEmailConfig } from '@/api/settings';
import { isValidEmail } from '@/lib/format';

// Email (dok. 12 §3.3–3.4):
//  - status SMTP + email uji coba (endpoint lama, sudah ada);
//  - penerima rekap harian HR (maks. 20, disimpan di DB; SMTP_TO dari env jadi bawaan);
//  - jam kirim rekap harian.
const MAX_RECIPIENTS = 20;

const props = defineProps({
  emailStatus: { type: Object, default: null },
  isSendingTestEmail: { type: Boolean, default: false },
});
const emit = defineEmits(['send-test', 'changed']);

const config = ref(null);
const recipients = ref([]);
const sendTime = ref('18:30');
const newRecipient = ref('');
const inputError = ref('');
const loading = ref(false);
const saving = ref(false);
const error = ref('');
const success = ref('');
const testResult = ref(null);

const dirty = computed(
  () =>
    !!config.value &&
    (JSON.stringify(recipients.value) !== JSON.stringify(config.value.recap_recipients) ||
      sendTime.value !== config.value.recap_send_time),
);
const usingEnvDefault = computed(() => recipients.value.length === 0);

async function load() {
  loading.value = true;
  error.value = '';
  try {
    config.value = await getEmailConfig();
    recipients.value = [...config.value.recap_recipients];
    sendTime.value = config.value.recap_send_time;
  } catch (err) {
    error.value = err?.message || 'Gagal memuat konfigurasi email.';
  } finally {
    loading.value = false;
  }
}
onMounted(load);

function addRecipient() {
  inputError.value = '';
  // Boleh menempel beberapa alamat sekaligus (dipisah koma / spasi / baris baru).
  const parts = newRecipient.value.split(/[\s,;]+/).map((p) => p.trim().toLowerCase()).filter(Boolean);
  if (!parts.length) return;
  const invalid = parts.filter((p) => !isValidEmail(p));
  if (invalid.length) {
    inputError.value = `Format tidak valid: ${invalid.join(', ')}`;
    return;
  }
  const fresh = parts.filter((p) => !recipients.value.includes(p));
  if (recipients.value.length + fresh.length > MAX_RECIPIENTS) {
    inputError.value = `Maksimal ${MAX_RECIPIENTS} penerima.`;
    return;
  }
  recipients.value.push(...fresh);
  newRecipient.value = '';
  if (fresh.length < parts.length) inputError.value = 'Alamat yang sudah ada tidak ditambahkan lagi.';
}

function removeRecipient(email) {
  recipients.value = recipients.value.filter((r) => r !== email);
}

function resetDraft() {
  recipients.value = [...config.value.recap_recipients];
  sendTime.value = config.value.recap_send_time;
  inputError.value = '';
}

async function save() {
  if (!/^\d{2}:\d{2}$/.test(sendTime.value)) {
    error.value = 'Jam kirim harus format HH:MM.';
    return;
  }
  saving.value = true;
  error.value = '';
  success.value = '';
  try {
    config.value = await saveEmailConfig({ recap_recipients: recipients.value, recap_send_time: sendTime.value });
    recipients.value = [...config.value.recap_recipients];
    sendTime.value = config.value.recap_send_time;
    success.value = 'Konfigurasi email rekap disimpan.';
    emit('changed');
  } catch (err) {
    error.value = err?.message || 'Gagal menyimpan konfigurasi email.';
  } finally {
    saving.value = false;
  }
}

async function sendTest() {
  testResult.value = null;
  emit('send-test', (result) => {
    testResult.value = result;
  });
}
</script>

<template>
  <div class="grid gap-6 lg:grid-cols-5">
    <Card class="lg:col-span-3">
      <CardHeader>
        <div class="flex items-center gap-2">
          <div class="rounded-lg bg-emerald-50 p-2 text-emerald-600"><Mail class="h-5 w-5" /></div>
          <div>
            <CardTitle class="text-base font-semibold">Email rekap harian (HR)</CardTitle>
            <CardDescription class="text-xs">
              Rekap semua karyawan dikirim sekali sehari dengan lampiran Excel.
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent class="space-y-5">
        <p v-if="loading && !config" class="py-6 text-center text-sm text-slate-400">Memuat…</p>
        <template v-if="config">
          <div class="space-y-1.5">
            <Label for="recap-time" class="text-xs font-semibold text-slate-700">Jam kirim rekap</Label>
            <input
              id="recap-time"
              v-model="sendTime"
              type="time"
              class="border-input h-9 w-32 rounded-md border bg-transparent px-2.5 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3"
            />
            <p class="text-[11px] text-slate-400">
              Sebaiknya setelah analisis kamera nonaktif. Rekap yang terlewat (server mati) dikirim susulan, tidak pernah ganda.
            </p>
          </div>

          <div class="space-y-1.5">
            <div class="flex items-center justify-between">
              <Label for="recap-new" class="text-xs font-semibold text-slate-700">Penerima rekap</Label>
              <span class="text-[11px] text-slate-400">{{ recipients.length }} / {{ MAX_RECIPIENTS }}</span>
            </div>
            <form class="flex gap-2" @submit.prevent="addRecipient">
              <Input id="recap-new" v-model="newRecipient" placeholder="hr@perusahaan.com (boleh beberapa, pisahkan koma)" />
              <Button type="submit" variant="outline" :disabled="!newRecipient.trim() || recipients.length >= MAX_RECIPIENTS">
                <Plus />
                Tambah
              </Button>
            </form>
            <p v-if="inputError" class="text-[11px] text-red-600">{{ inputError }}</p>
            <div class="flex min-h-10 flex-wrap gap-1.5 rounded-md border border-dashed p-2">
              <span
                v-for="email in recipients"
                :key="email"
                class="inline-flex items-center gap-1 rounded-full bg-slate-100 py-0.5 pr-1 pl-2.5 font-mono text-xs text-slate-700"
              >
                {{ email }}
                <button type="button" class="rounded-full p-0.5 text-slate-400 hover:bg-slate-200 hover:text-red-600" :aria-label="`Hapus ${email}`" @click="removeRecipient(email)">
                  <X class="h-3 w-3" />
                </button>
              </span>
              <span v-if="usingEnvDefault" class="text-xs text-amber-700">
                Daftar kosong → memakai bawaan dari server (SMTP_TO):
                <span class="font-mono">{{ config.default_from_env?.join(', ') || 'tidak ada' }}</span>
              </span>
            </div>
            <p class="text-[11px] text-slate-400">
              Email per pelanggaran dikirim ke karyawan + CC daftar ini; karyawan tanpa email → daftar ini saja.
            </p>
          </div>
        </template>

        <div v-if="error" class="flex items-start gap-2 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">
          <AlertCircle class="mt-0.5 h-3.5 w-3.5 shrink-0" />{{ error }}
        </div>
        <div v-if="success" class="flex items-start gap-2 rounded-md bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
          <CheckCircle2 class="mt-0.5 h-3.5 w-3.5 shrink-0" />{{ success }}
        </div>
      </CardContent>
      <CardFooter class="flex justify-end gap-2 border-t border-slate-100 pt-4">
        <Button variant="ghost" size="sm" :disabled="!dirty || saving" @click="resetDraft">
          <RotateCcw />
          Batalkan perubahan
        </Button>
        <Button size="sm" :disabled="!dirty || saving" @click="save">
          <Save />
          {{ saving ? 'Menyimpan…' : 'Simpan' }}
        </Button>
      </CardFooter>
    </Card>

    <Card class="lg:col-span-2">
      <CardHeader>
        <div class="flex items-center gap-2">
          <div class="rounded-lg bg-slate-100 p-2 text-slate-700"><Server class="h-5 w-5" /></div>
          <div>
            <CardTitle class="text-base font-semibold">Status SMTP</CardTitle>
            <CardDescription class="text-xs">Akun pengirim diatur di server (env).</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent class="space-y-3 text-xs">
        <div class="flex items-center justify-between">
          <span class="font-semibold text-slate-700">Layanan</span>
          <Badge :class="props.emailStatus?.enabled ? 'bg-emerald-600 text-white' : 'bg-slate-200 text-slate-600'">
            {{ props.emailStatus?.enabled ? 'Aktif' : 'Nonaktif' }}
          </Badge>
        </div>
        <div class="flex items-center justify-between">
          <span class="font-semibold text-slate-700">Worker</span>
          <span :class="props.emailStatus?.worker_running ? 'text-emerald-600' : 'text-amber-600'">
            {{ props.emailStatus?.worker_running ? 'Berjalan' : 'Tidak berjalan' }}
          </span>
        </div>
        <div class="flex items-center justify-between gap-2">
          <span class="font-semibold text-slate-700">Server</span>
          <span class="truncate font-mono text-slate-600">{{ props.emailStatus?.host || '-' }}:{{ props.emailStatus?.port || '-' }}</span>
        </div>
        <div class="flex items-center justify-between gap-2">
          <span class="font-semibold text-slate-700">Pengirim</span>
          <span class="truncate font-mono text-slate-600">{{ props.emailStatus?.from || '-' }}</span>
        </div>
        <div
          v-if="testResult"
          class="rounded-md px-3 py-2"
          :class="testResult.success ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-700'"
        >
          {{ testResult.message }}
        </div>
      </CardContent>
      <CardFooter class="border-t border-slate-100 pt-4">
        <Button variant="outline" size="sm" class="w-full" :disabled="isSendingTestEmail" @click="sendTest">
          <Send :class="isSendingTestEmail && 'animate-pulse'" />
          {{ isSendingTestEmail ? 'Mengirim…' : 'Kirim email uji coba' }}
        </Button>
      </CardFooter>
    </Card>
  </div>
</template>
