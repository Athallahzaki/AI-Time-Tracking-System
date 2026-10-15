<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { AlertTriangle, Bell, Check, Clock, MapPin, RefreshCw } from '@lucide/vue';
import DashboardLayout from '@/layouts/DashboardLayout.vue';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import StatusBadge from '@/components/common/StatusBadge.vue';
import DataSourceBanner from '@/components/common/DataSourceBanner.vue';
import { getMyUsageToday } from '@/api/me';
import { apiSources } from '@/api/http';
import { employeeIdOf, useAuth } from '@/composables/useAuth';
import { useNotifications } from '@/composables/useNotifications';
import { STATUS_META, formatDate, formatDuration, formatTime } from '@/lib/format';

// Tampilan karyawan (viewer, dok. 12 §3.2): hanya pemakaian free time miliknya
// hari ini + notifikasi miliknya. Tidak ada live feed, tidak ada data orang lain.
const REFRESH_MS = 60_000;

const { user } = useAuth();
const { notifications, unreadCount, markAsRead, isLoading: notifLoading } = useNotifications();

const usage = ref(null);
const loading = ref(false);
const error = ref('');
let timer = null;

const employeeId = computed(() => employeeIdOf(user.value) || '');
const displayName = computed(() => user.value?.name || usage.value?.name || user.value?.username || '');

const percent = computed(() => {
  if (!usage.value?.allowance_seconds) return 0;
  return Math.min(100, Math.round((usage.value.used_seconds / usage.value.allowance_seconds) * 100));
});
const overBy = computed(() =>
  usage.value ? Math.max(0, usage.value.used_seconds - usage.value.allowance_seconds) : 0,
);
const locationsSorted = computed(() =>
  [...(usage.value?.by_location || [])].sort((a, b) => b.seconds - a.seconds),
);
const sourceNote = computed(() =>
  apiSources.me === 'mock'
    ? 'Endpoint /api/me/usage-today belum ada; angka diambil dari data pemakaian yang tersedia atau disimulasikan.'
    : '',
);

async function load() {
  if (!employeeId.value) return;
  loading.value = true;
  error.value = '';
  try {
    usage.value = await getMyUsageToday(employeeId.value, user.value?.name || user.value?.username || '');
  } catch (err) {
    error.value = err?.message || 'Gagal memuat pemakaian hari ini.';
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  load();
  timer = setInterval(load, REFRESH_MS);
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
});

// Notifikasi baru (mis. peringatan) → segarkan angka pemakaian.
watch(
  () => notifications.value.length,
  (now, before) => {
    if (before !== undefined && now > before) load();
  },
);

function notifTime(n) {
  const ts = n.event_at || n.created_at;
  if (!ts) return '-';
  const d = new Date(ts * 1000);
  return d.toLocaleString('id-ID', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function isWarning(n) {
  return /warn|peringatan/i.test(`${n.type} ${n.title}`);
}
</script>

<template>
  <DashboardLayout :crumbs="['Karyawan', 'Pemakaian Saya']">
    <div class="mx-auto max-w-3xl space-y-5">
      <div class="flex items-start justify-between gap-3">
        <div>
          <h1 class="text-xl font-bold tracking-tight text-slate-900 sm:text-2xl">Halo, {{ displayName }}</h1>
          <p class="mt-1 text-sm text-slate-500">
            Pemakaian free time Anda hari ini, {{ formatDate(usage?.date) }}.
          </p>
        </div>
        <Button variant="outline" size="sm" :disabled="loading" @click="load">
          <RefreshCw :class="loading && 'animate-spin'" />
          <span class="hidden sm:inline">Muat ulang</span>
        </Button>
      </div>

      <DataSourceBanner :domains="['me']" :note="sourceNote" />

      <p v-if="!employeeId" class="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">
        Akun ini belum terhubung ke data karyawan. Hubungi HR.
      </p>
      <p v-if="error" class="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{{ error }}</p>

      <Card v-if="usage" class="gap-4">
        <CardHeader class="pb-0">
          <div class="flex items-center justify-between gap-2">
            <CardTitle class="flex items-center gap-2 text-base">
              <Clock class="h-5 w-5 text-indigo-600" />
              Free time hari ini
            </CardTitle>
            <StatusBadge :status="usage.status" />
          </div>
        </CardHeader>
        <CardContent class="space-y-5">
          <div>
            <div class="flex items-end justify-between gap-2">
              <p class="text-3xl font-bold text-slate-900 tabular-nums sm:text-4xl">
                {{ formatDuration(usage.used_seconds) }}
                <span class="text-base font-normal text-slate-400">/ {{ formatDuration(usage.allowance_seconds) }}</span>
              </p>
              <p class="text-right text-sm" :class="overBy ? 'font-semibold text-red-600' : 'text-slate-600'">
                <template v-if="overBy">Lewat {{ formatDuration(overBy) }}</template>
                <template v-else>Sisa {{ formatDuration(usage.remaining_seconds) }}</template>
              </p>
            </div>
            <div class="mt-3 h-3 overflow-hidden rounded-full bg-slate-100" role="progressbar" :aria-valuenow="percent" aria-valuemin="0" aria-valuemax="100">
              <div class="h-full rounded-full transition-all" :class="STATUS_META[usage.status]?.bar" :style="{ width: `${percent}%` }" />
            </div>
          </div>

          <div class="grid grid-cols-2 gap-3 text-sm">
            <div class="rounded-lg bg-slate-50 px-3 py-2.5">
              <p class="text-xs text-slate-500">Kunjungan</p>
              <p class="mt-0.5 font-semibold text-slate-900">{{ usage.visits }} kali</p>
            </div>
            <div class="rounded-lg bg-slate-50 px-3 py-2.5">
              <p class="text-xs text-slate-500">Pertama terlihat</p>
              <p class="mt-0.5 font-semibold text-slate-900">{{ formatTime(usage.first_seen_at) }}</p>
            </div>
          </div>

          <div v-if="locationsSorted.length">
            <p class="mb-2 flex items-center gap-1.5 text-xs font-semibold text-slate-600">
              <MapPin class="h-3.5 w-3.5" /> Rincian lokasi
            </p>
            <ul class="space-y-1.5">
              <li v-for="loc in locationsSorted" :key="loc.location" class="flex items-center gap-3 text-sm">
                <span class="w-32 shrink-0 truncate text-slate-700">{{ loc.location }}</span>
                <div class="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                  <div
                    class="h-full rounded-full bg-indigo-400"
                    :style="{ width: `${usage.used_seconds ? Math.round((loc.seconds / usage.used_seconds) * 100) : 0}%` }"
                  />
                </div>
                <span class="w-16 shrink-0 text-right text-xs text-slate-500 tabular-nums">{{ formatDuration(loc.seconds) }}</span>
              </li>
            </ul>
          </div>
          <p v-else class="text-sm text-slate-400">Belum ada kunjungan ke area rekreasi hari ini.</p>

          <p class="text-[11px] text-slate-400">
            Jam istirahat resmi tidak dihitung. Kunjungan singkat (orang lewat) tidak memotong jatah.
            Angka diperbarui tiap menit.
          </p>
        </CardContent>
      </Card>
      <Card v-else-if="loading" class="h-56 animate-pulse bg-slate-100" />

      <Card class="gap-3">
        <CardHeader class="pb-0">
          <div class="flex items-center justify-between">
            <CardTitle class="flex items-center gap-2 text-base">
              <Bell class="h-5 w-5 text-indigo-600" />
              Notifikasi saya
            </CardTitle>
            <span v-if="unreadCount" class="rounded-full bg-rose-100 px-2 py-0.5 text-xs font-semibold text-rose-700">{{ unreadCount }} baru</span>
          </div>
          <CardDescription class="text-xs">Peringatan dan pelanggaran batas free time milik Anda.</CardDescription>
        </CardHeader>
        <CardContent>
          <p v-if="notifLoading && !notifications.length" class="py-6 text-center text-sm text-slate-400">Memuat…</p>
          <p v-else-if="!notifications.length" class="py-6 text-center text-sm text-slate-400">Belum ada notifikasi. Bagus.</p>
          <ul class="divide-y">
            <li v-for="n in notifications" :key="n.id" class="flex items-start gap-3 py-3" :class="!n.read && 'bg-indigo-50/40 -mx-2 px-2 rounded'">
              <div
                class="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
                :class="isWarning(n) ? 'bg-amber-100 text-amber-700' : 'bg-red-100 text-red-700'"
              >
                <AlertTriangle class="h-4 w-4" />
              </div>
              <div class="min-w-0 flex-1">
                <p class="text-sm font-semibold text-slate-900">{{ n.title }}</p>
                <p class="text-sm text-slate-600">{{ n.message }}</p>
                <p class="mt-0.5 text-[11px] text-slate-400">{{ notifTime(n) }}</p>
              </div>
              <Button v-if="!n.read" variant="ghost" size="icon-sm" title="Tandai sudah dibaca" aria-label="Tandai sudah dibaca" @click="markAsRead(n.id)">
                <Check />
              </Button>
            </li>
          </ul>
        </CardContent>
      </Card>
    </div>
  </DashboardLayout>
</template>
