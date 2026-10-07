<script setup lang="ts">
import { ref, onMounted, watch } from 'vue';
import DashboardLayout from '@/layouts/DashboardLayout.vue';
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertTitle } from '@/components/ui/alert';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useSettings } from '@/composables/useSettings';
import {
  Clock,
  Mail,
  CheckCircle2,
  AlertCircle,
  Send,
  Save,
  RefreshCw,
} from '@lucide/vue';

const {
  policy,
  emailStatus,
  isLoading,
  isSaving,
  isSendingTestEmail,
  error,
  successMessage,
  fetchPolicy,
  updatePolicy,
  fetchEmailStatus,
  sendTestEmail,
} = useSettings();

const dailyAllowance = ref<number | string>(60);
const warningThreshold = ref<number | string>(10);
const emailAlert = ref<{ type: 'success' | 'error'; text: string } | null>(
  null,
);

onMounted(() => {
  fetchPolicy();
  fetchEmailStatus();
});

watch(policy, (p) => {
  if (p) {
    dailyAllowance.value = p.daily_free_time_allowance_minutes;
    warningThreshold.value = p.warning_remaining_minutes;
  }
});

async function handleSavePolicy() {
  emailAlert.value = null;
  // Input shadcn bisa mengembalikan string; pastikan yang dikirim tetap angka.
  await updatePolicy(
    Number(dailyAllowance.value),
    Number(warningThreshold.value),
  );
}

async function handleSendTestEmail() {
  emailAlert.value = null;
  const res = await sendTestEmail();
  emailAlert.value = {
    type: res.success ? 'success' : 'error',
    text: res.message,
  };
}
</script>

<template>
  <DashboardLayout :crumbs="['Dashboard', 'Pengaturan Sistem']">
    <div class="max-w-5xl mx-auto space-y-6">
      <!-- Title & Header -->
      <div
        class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4"
      >
        <div>
          <h1 class="text-2xl font-bold tracking-tight text-slate-900">
            Pengaturan Sistem
          </h1>
          <p class="text-sm text-slate-500 mt-1">
            Konfigurasi batas jatah waktu karyawan, notifikasi, dan integrasi
            pengiriman email SMTP.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          class="self-start sm:self-auto"
          @click="
            () => {
              fetchPolicy();
              fetchEmailStatus();
            }
          "
          :disabled="isLoading"
        >
          <RefreshCw class="h-4 w-4" :class="isLoading ? 'animate-spin' : ''" />
          Muat Ulang
        </Button>
      </div>

      <!-- Feedback Global Alert -->
      <Alert
        v-if="error"
        variant="destructive"
        class="border-red-200 bg-red-50"
      >
        <AlertCircle />
        <AlertTitle class="line-clamp-none">{{ error }}</AlertTitle>
      </Alert>

      <Alert v-if="successMessage" variant="success">
        <CheckCircle2 />
        <AlertTitle class="line-clamp-none">{{ successMessage }}</AlertTitle>
      </Alert>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- 1. Card: Kebijakan Jatah Free Time -->
        <Card class="flex flex-col justify-between">
          <div>
            <CardHeader>
              <div class="flex items-center gap-2">
                <div class="p-2 rounded-lg bg-indigo-50 text-indigo-600">
                  <Clock class="h-5 w-5" />
                </div>
                <div>
                  <CardTitle class="text-base font-semibold"
                    >Batas Jatah Waktu Istirahat (Free Time)</CardTitle
                  >
                  <CardDescription class="text-xs">
                    Pengaturan jatah maksimal karyawan dan ambang batas
                    peringatan sistem.
                  </CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent class="space-y-4">
              <div class="space-y-1.5">
                <Label
                  for="daily-allowance"
                  class="text-xs font-semibold text-slate-700"
                >
                  Jatah Harian Karyawan (Menit)
                </Label>
                <div class="relative">
                  <Input
                    id="daily-allowance"
                    v-model="dailyAllowance"
                    type="number"
                    min="1"
                    max="1440"
                    class="pr-28"
                    placeholder="Contoh: 60"
                  />
                  <span
                    class="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-xs text-slate-400"
                    >menit/hari</span
                  >
                </div>
                <p class="text-[11px] text-slate-400">
                  Total waktu bebas di luar jam kerja resmi sebelum dianggap
                  melanggar (exceeded).
                </p>
              </div>

              <div class="space-y-1.5">
                <Label
                  for="warning-threshold"
                  class="text-xs font-semibold text-slate-700"
                >
                  Ambang Peringatan / Warning Threshold (Sisa Menit)
                </Label>
                <div class="relative">
                  <Input
                    id="warning-threshold"
                    v-model="warningThreshold"
                    type="number"
                    min="0"
                    :max="dailyAllowance"
                    class="pr-28"
                    placeholder="Contoh: 10"
                  />
                  <span
                    class="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-xs text-slate-400"
                    >menit tersisa</span
                  >
                </div>
                <p class="text-[11px] text-slate-400">
                  Status akan berubah menjadi <strong>Warning</strong> saat sisa
                  jatah kurang dari angka ini.
                </p>
              </div>

              <div
                v-if="policy"
                class="mt-4 p-3 rounded-lg bg-slate-50 border border-slate-100 text-xs space-y-1 text-slate-600"
              >
                <div class="flex justify-between">
                  <span>Zona Waktu:</span>
                  <span class="font-medium text-slate-800">{{
                    policy.timezone
                  }}</span>
                </div>
                <div class="flex justify-between">
                  <span>Istirahat Resmi:</span>
                  <span class="font-medium text-slate-800">
                    {{
                      policy.official_breaks
                        ?.map((b) => `${b.start}-${b.end}`)
                        .join(', ') || '-'
                    }}
                  </span>
                </div>
              </div>
            </CardContent>
          </div>
          <CardFooter class="border-t border-slate-100 pt-4 flex justify-end">
            <Button @click="handleSavePolicy" :disabled="isSaving">
              <Save class="h-4 w-4" />
              {{ isSaving ? 'Menyimpan...' : 'Simpan Perubahan' }}
            </Button>
          </CardFooter>
        </Card>

        <!-- 2. Card: Notifikasi & Integrasi Email -->
        <Card class="flex flex-col justify-between">
          <div>
            <CardHeader>
              <div class="flex items-center gap-2">
                <div class="p-2 rounded-lg bg-emerald-50 text-emerald-600">
                  <Mail class="h-5 w-5" />
                </div>
                <div>
                  <CardTitle class="text-base font-semibold"
                    >Integrasi Email (SMTP Alert)</CardTitle
                  >
                  <CardDescription class="text-xs">
                    Status pengiriman email otomatis saat terjadi pelanggaran
                    jatah waktu.
                  </CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent class="space-y-4">
              <!-- Status Badge Summary -->
              <div
                class="p-4 rounded-xl border border-slate-100 bg-slate-50/60 space-y-3"
              >
                <div class="flex items-center justify-between">
                  <span class="text-xs font-semibold text-slate-700"
                    >Status SMTP Service:</span
                  >
                  <Badge
                    :variant="emailStatus?.enabled ? 'default' : 'secondary'"
                    :class="
                      emailStatus?.enabled
                        ? 'bg-emerald-600 text-white'
                        : 'bg-slate-200 text-slate-600'
                    "
                  >
                    {{ emailStatus?.enabled ? 'Aktif' : 'Nonaktif' }}
                  </Badge>
                </div>

                <div class="flex items-center justify-between">
                  <span class="text-xs font-semibold text-slate-700"
                    >Worker Pengiriman:</span
                  >
                  <span
                    class="text-xs font-medium"
                    :class="
                      emailStatus?.worker_running
                        ? 'text-emerald-600'
                        : 'text-amber-600'
                    "
                  >
                    {{
                      emailStatus?.worker_running
                        ? 'Berjalan (Ready)'
                        : 'Tidak Berjalan'
                    }}
                  </span>
                </div>

                <div class="flex items-center justify-between">
                  <span class="text-xs font-semibold text-slate-700"
                    >Server Host:</span
                  >
                  <span class="text-xs font-mono text-slate-600">
                    {{ emailStatus?.host || '-' }}:{{
                      emailStatus?.port || '-'
                    }}
                  </span>
                </div>

                <div class="space-y-1">
                  <span class="text-xs font-semibold text-slate-700 block"
                    >Penerima Notifikasi:</span
                  >
                  <div class="flex flex-wrap gap-1">
                    <template
                      v-if="
                        emailStatus?.recipients &&
                        emailStatus.recipients.length > 0
                      "
                    >
                      <Badge
                        v-for="rec in emailStatus.recipients"
                        :key="rec"
                        variant="secondary"
                        class="text-[11px] font-mono"
                      >
                        {{ rec }}
                      </Badge>
                    </template>
                    <span v-else class="text-xs text-slate-400 italic"
                      >Belum ada penerima disetel</span
                    >
                  </div>
                </div>
              </div>

              <!-- Email Alert Message -->
              <Alert
                v-if="emailAlert"
                :variant="
                  emailAlert.type === 'success' ? 'success' : 'destructive'
                "
                :class="
                  emailAlert.type === 'error' && 'border-red-200 bg-red-50'
                "
              >
                <component
                  :is="
                    emailAlert.type === 'success' ? CheckCircle2 : AlertCircle
                  "
                />
                <AlertTitle class="line-clamp-none text-xs">{{
                  emailAlert.text
                }}</AlertTitle>
              </Alert>
            </CardContent>
          </div>
          <CardFooter
            class="border-t border-slate-100 pt-4 flex items-center justify-between"
          >
            <span class="text-[11px] text-slate-400">
              Kirim email percobaan ke daftar penerima
            </span>
            <Button
              variant="outline"
              size="sm"
              @click="handleSendTestEmail"
              :disabled="isSendingTestEmail"
            >
              <Send
                class="h-3.5 w-3.5"
                :class="isSendingTestEmail ? 'animate-pulse' : ''"
              />
              {{ isSendingTestEmail ? 'Mengirim...' : 'Kirim Email Uji Coba' }}
            </Button>
          </CardFooter>
        </Card>
      </div>
    </div>
  </DashboardLayout>
</template>
