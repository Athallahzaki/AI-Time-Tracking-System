<script setup>
import { computed, onMounted, ref } from 'vue';
import {
  AlertTriangle,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  Download,
  FileText,
  RefreshCw,
} from '@lucide/vue';
import DashboardLayout from '@/layouts/DashboardLayout.vue';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { tableClass } from '@/components/ui/table';
import DataSourceBanner from '@/components/common/DataSourceBanner.vue';
import EmployeeCombobox from '@/components/common/EmployeeCombobox.vue';
import StatusBadge from '@/components/common/StatusBadge.vue';
import { nativeSelectClass } from '@/components/common/nativeSelect';
import VisitTimeline from '@/components/reports/VisitTimeline.vue';
import { MAX_RANGE_DAYS, exportReportXlsx, getDailyReport, getVisits } from '@/api/reports';
import { listDivisions } from '@/api/employees';
import { localDateString } from '@/api/mock/db';
import { formatDate, formatDuration, formatTime } from '@/lib/format';

// Halaman report (dok. 12 §3.5): per karyawan per hari — terpakai, sisa,
// kunjungan, rincian lokasi, status, menit dari ReID; filter rentang tanggal;
// export .xlsx (generator di BE; cadangan di browser selama BE belum siap).
const PAGE_SIZE = 50;

function shiftDays(days) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return localDateString(d);
}

const today = localDateString();
const filters = ref({ from: today, to: today, division: '', employee_uid: '', status: '' });
const preset = ref('today');
const divisions = ref([]);

const report = ref(null);
const page = ref(1);
const loading = ref(false);
const error = ref('');
const exporting = ref(false);
const exportMessage = ref('');

const expanded = ref({});
const visits = ref({});

const PRESETS = [
  { id: 'today', label: 'Hari ini', range: () => [today, today] },
  { id: 'yesterday', label: 'Kemarin', range: () => [shiftDays(-1), shiftDays(-1)] },
  { id: '7d', label: '7 hari', range: () => [shiftDays(-6), today] },
  {
    id: 'month',
    label: 'Bulan ini',
    range: () => {
      const d = new Date();
      return [localDateString(new Date(d.getFullYear(), d.getMonth(), 1)), today];
    },
  },
];

const rangeDays = computed(() => {
  const a = new Date(`${filters.value.from}T00:00:00`);
  const b = new Date(`${filters.value.to}T00:00:00`);
  return Math.round((b - a) / 86400000) + 1;
});
const rangeError = computed(() => {
  if (!filters.value.from || !filters.value.to) return 'Isi tanggal mulai dan selesai.';
  if (rangeDays.value < 1) return 'Tanggal selesai harus sama atau setelah tanggal mulai.';
  if (rangeDays.value > MAX_RANGE_DAYS) return `Rentang maksimal ${MAX_RANGE_DAYS} hari per permintaan.`;
  return '';
});
const totalPages = computed(() => Math.max(1, Math.ceil((report.value?.total || 0) / PAGE_SIZE)));
const showReidColumn = computed(() => (report.value?.items || []).some((r) => r.reid_seconds > 0));

function applyPreset(id) {
  const p = PRESETS.find((x) => x.id === id);
  if (!p) return;
  preset.value = id;
  const [from, to] = p.range();
  filters.value.from = from;
  filters.value.to = to;
  load(1);
}

function onDateInput() {
  preset.value = '';
}

async function load(targetPage = page.value) {
  if (rangeError.value) return;
  loading.value = true;
  error.value = '';
  page.value = targetPage;
  expanded.value = {};
  try {
    report.value = await getDailyReport(filters.value, page.value, PAGE_SIZE);
  } catch (err) {
    error.value = err?.message || 'Gagal memuat report.';
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  load(1);
  try {
    divisions.value = await listDivisions();
  } catch {
    divisions.value = [];
  }
});

function rowKey(r) {
  return `${r.employee_uid}:${r.date}`;
}

async function toggleRow(r) {
  const key = rowKey(r);
  expanded.value[key] = !expanded.value[key];
  if (!expanded.value[key] || visits.value[key]?.items) return;
  visits.value[key] = { loading: true, items: null, error: '' };
  try {
    visits.value[key] = { loading: false, items: await getVisits(r.employee_uid, r.date), error: '' };
  } catch (err) {
    visits.value[key] = { loading: false, items: [], error: err?.message || 'Gagal memuat kunjungan.' };
  }
}

async function handleExport() {
  if (rangeError.value) return;
  exporting.value = true;
  exportMessage.value = '';
  try {
    const res = await exportReportXlsx(filters.value);
    exportMessage.value =
      res.generatedBy === 'browser'
        ? `${res.filename} dibuat di browser (sementara, BE belum punya generator Excel).`
        : `${res.filename} diunduh.`;
  } catch (err) {
    exportMessage.value = err?.message || 'Gagal membuat file Excel.';
  } finally {
    exporting.value = false;
  }
}

function usedPercent(r) {
  return r.allowance_seconds ? Math.min(100, Math.round((r.used_seconds / r.allowance_seconds) * 100)) : 0;
}
</script>

<template>
  <DashboardLayout :crumbs="['Laporan', 'Report Free Time']">
    <div class="mx-auto max-w-7xl space-y-5">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 class="flex items-center gap-2 text-2xl font-bold tracking-tight text-slate-900">
            <FileText class="h-6 w-6 text-indigo-600" />
            Report Free Time
          </h1>
          <p class="mt-1 text-sm text-slate-500">
            Total free time per karyawan per hari, rincian lokasi, dan status batas.
          </p>
        </div>
        <Button class="bg-emerald-600 hover:bg-emerald-700" size="sm" :disabled="exporting || !!rangeError" @click="handleExport">
          <Download :class="exporting && 'animate-bounce'" />
          {{ exporting ? 'Menyiapkan file…' : 'Export Excel' }}
        </Button>
      </div>

      <DataSourceBanner :domains="['reports', 'reports-xlsx', 'employees']" />
      <p
        v-if="exportMessage"
        class="rounded-md bg-slate-100 px-3 py-2 text-xs text-slate-700"
      >{{ exportMessage }}</p>

      <!-- Filter -->
      <Card class="gap-3 p-4 shadow-xs">
        <div class="flex flex-wrap gap-1.5">
          <Button
            v-for="p in PRESETS"
            :key="p.id"
            size="xs"
            :variant="preset === p.id ? 'default' : 'outline'"
            @click="applyPreset(p.id)"
          >{{ p.label }}</Button>
        </div>
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
          <div class="space-y-1">
            <Label for="rep-from" class="text-xs text-slate-600">Dari</Label>
            <input id="rep-from" v-model="filters.from" type="date" :max="today" :class="nativeSelectClass" @input="onDateInput" />
          </div>
          <div class="space-y-1">
            <Label for="rep-to" class="text-xs text-slate-600">Sampai</Label>
            <input id="rep-to" v-model="filters.to" type="date" :max="today" :class="nativeSelectClass" @input="onDateInput" />
          </div>
          <div class="space-y-1">
            <Label for="rep-division" class="text-xs text-slate-600">Divisi</Label>
            <select id="rep-division" v-model="filters.division" :class="nativeSelectClass">
              <option value="">Semua divisi</option>
              <option v-for="d in divisions" :key="d" :value="d">{{ d }}</option>
            </select>
          </div>
          <div class="space-y-1 lg:col-span-2">
            <Label for="rep-employee" class="text-xs text-slate-600">Karyawan</Label>
            <EmployeeCombobox id="rep-employee" v-model="filters.employee_uid" :active-only="false" allow-clear />
          </div>
          <div class="space-y-1">
            <Label for="rep-status" class="text-xs text-slate-600">Status</Label>
            <select id="rep-status" v-model="filters.status" :class="nativeSelectClass">
              <option value="">Semua status</option>
              <option value="safe">Aman</option>
              <option value="warning">Peringatan</option>
              <option value="exceeded">Lewat batas</option>
            </select>
          </div>
        </div>
        <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p class="text-xs" :class="rangeError ? 'text-red-600' : 'text-slate-400'">
            {{ rangeError || `${rangeDays} hari dipilih` }}
          </p>
          <Button size="sm" :disabled="loading || !!rangeError" @click="load(1)">
            <RefreshCw :class="loading && 'animate-spin'" />
            Tampilkan
          </Button>
        </div>
      </Card>

      <!-- Ringkasan -->
      <div v-if="report" class="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <div class="rounded-xl border bg-white px-4 py-3">
          <p class="text-xs text-slate-500">Karyawan terpantau</p>
          <p class="mt-1 text-2xl font-semibold text-slate-900">{{ report.summary.employees }}</p>
        </div>
        <div class="rounded-xl border bg-white px-4 py-3">
          <p class="text-xs text-slate-500">Baris (karyawan × hari)</p>
          <p class="mt-1 text-2xl font-semibold text-slate-900">{{ report.summary.rows }}</p>
        </div>
        <div class="rounded-xl border bg-white px-4 py-3">
          <p class="text-xs text-slate-500">Lewat batas</p>
          <p class="mt-1 text-2xl font-semibold" :class="report.summary.exceeded ? 'text-red-600' : 'text-slate-900'">{{ report.summary.exceeded }}</p>
        </div>
        <div class="rounded-xl border bg-white px-4 py-3">
          <p class="text-xs text-slate-500">Rata-rata terpakai</p>
          <p class="mt-1 text-2xl font-semibold text-slate-900">{{ formatDuration(report.summary.avg_used_seconds) }}</p>
        </div>
        <RouterLink
          to="/reviews"
          class="col-span-2 rounded-xl border bg-white px-4 py-3 transition-colors hover:border-amber-300 lg:col-span-1"
        >
          <p class="flex items-center gap-1 text-xs text-slate-500"><ClipboardCheck class="h-3.5 w-3.5" />Perlu dicek HR</p>
          <p class="mt-1 text-2xl font-semibold" :class="report.summary.needs_review ? 'text-amber-600' : 'text-slate-900'">{{ report.summary.needs_review }}</p>
        </RouterLink>
      </div>

      <p v-if="error" class="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{{ error }}</p>

      <!-- Tabel -->
      <Card class="gap-0 py-0 shadow-xs">
        <div :class="tableClass.wrapper">
          <table :class="tableClass.table">
            <thead :class="tableClass.thead">
              <tr>
                <th :class="tableClass.th" class="w-8"><span class="sr-only">Rincian</span></th>
                <th :class="tableClass.th">Tanggal</th>
                <th :class="tableClass.th">Karyawan</th>
                <th :class="tableClass.th" class="hidden lg:table-cell">Divisi</th>
                <th :class="tableClass.th">Terpakai</th>
                <th :class="tableClass.th" class="hidden sm:table-cell">Sisa</th>
                <th :class="tableClass.th" class="hidden md:table-cell">Kunjungan</th>
                <th :class="tableClass.th" class="hidden xl:table-cell">Pertama terlihat</th>
                <th v-if="showReidColumn" :class="tableClass.th" class="hidden md:table-cell">Dari ReID</th>
                <th :class="tableClass.th">Status</th>
              </tr>
            </thead>
            <tbody :class="tableClass.tbody">
              <tr v-if="loading && !report">
                <td colspan="10" class="px-3 py-10 text-center text-sm text-slate-400">Memuat report…</td>
              </tr>
              <tr v-else-if="report && !report.items.length">
                <td colspan="10" class="px-3 py-10 text-center text-sm text-slate-400">
                  Tidak ada pemakaian free time pada rentang dan filter ini.
                </td>
              </tr>
              <template v-for="r in report?.items || []" :key="rowKey(r)">
                <tr :class="[tableClass.tr, 'cursor-pointer']" @click="toggleRow(r)">
                  <td :class="tableClass.td">
                    <ChevronDown class="h-4 w-4 text-slate-400 transition-transform" :class="expanded[rowKey(r)] && 'rotate-180'" />
                  </td>
                  <td :class="tableClass.td" class="text-xs whitespace-nowrap text-slate-600">{{ formatDate(r.date) }}</td>
                  <td :class="tableClass.td">
                    <p class="font-medium text-slate-900">{{ r.name }}</p>
                    <p class="font-mono text-[11px] text-slate-400">{{ r.employee_id }}</p>
                  </td>
                  <td :class="tableClass.td" class="hidden text-slate-600 lg:table-cell">{{ r.division || '—' }}</td>
                  <td :class="tableClass.td">
                    <p class="font-semibold text-slate-900 tabular-nums">{{ formatDuration(r.used_seconds) }}</p>
                    <div class="mt-1 h-1.5 w-20 overflow-hidden rounded-full bg-slate-100">
                      <div
                        class="h-full rounded-full"
                        :class="r.status === 'exceeded' ? 'bg-red-500' : r.status === 'warning' ? 'bg-amber-500' : 'bg-emerald-500'"
                        :style="{ width: `${usedPercent(r)}%` }"
                      />
                    </div>
                  </td>
                  <td :class="tableClass.td" class="hidden text-slate-600 tabular-nums sm:table-cell">{{ formatDuration(r.remaining_seconds) }}</td>
                  <td :class="tableClass.td" class="hidden text-slate-600 md:table-cell">{{ r.visits }}</td>
                  <td :class="tableClass.td" class="hidden text-slate-600 xl:table-cell">{{ formatTime(r.first_seen_at) }}</td>
                  <td v-if="showReidColumn" :class="tableClass.td" class="hidden md:table-cell">
                    <span v-if="r.reid_seconds" class="text-xs font-medium text-violet-700">{{ formatDuration(r.reid_seconds) }}</span>
                    <span v-else class="text-xs text-slate-300">—</span>
                  </td>
                  <td :class="tableClass.td">
                    <div class="flex flex-col items-start gap-1">
                      <StatusBadge :status="r.status" />
                      <span
                        v-if="r.needs_review"
                        class="inline-flex items-center gap-1 rounded-full bg-amber-50 px-1.5 text-[10px] font-semibold text-amber-700"
                        title="Sebagian besar menit bersumber ReID"
                      >
                        <AlertTriangle class="h-3 w-3" /> perlu dicek
                      </span>
                    </div>
                  </td>
                </tr>
                <tr v-if="expanded[rowKey(r)]" class="border-b bg-slate-50/60">
                  <td colspan="10" class="px-4 py-3 sm:px-12">
                    <div class="grid gap-4 md:grid-cols-[16rem_1fr]">
                      <div>
                        <p class="mb-2 text-xs font-semibold text-slate-600">Per lokasi</p>
                        <ul class="space-y-1 text-xs">
                          <li v-for="l in r.by_location" :key="l.location" class="flex justify-between gap-3">
                            <span class="text-slate-600">{{ l.location }}</span>
                            <span class="font-medium text-slate-800 tabular-nums">{{ formatDuration(l.seconds) }}</span>
                          </li>
                          <li v-if="!r.by_location.length" class="text-slate-400">—</li>
                        </ul>
                      </div>
                      <div>
                        <p class="mb-2 text-xs font-semibold text-slate-600">Kunjungan</p>
                        <VisitTimeline
                          :segments="visits[rowKey(r)]?.items || []"
                          :loading="!!visits[rowKey(r)]?.loading"
                          :error="visits[rowKey(r)]?.error || ''"
                        />
                      </div>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
        <div v-if="report" class="flex items-center justify-between gap-2 border-t px-4 py-2.5 text-xs text-slate-500">
          <span>{{ report.total }} baris · halaman {{ page }} / {{ totalPages }}</span>
          <div class="flex gap-1">
            <Button variant="outline" size="icon-sm" :disabled="page <= 1 || loading" aria-label="Halaman sebelumnya" @click="load(page - 1)">
              <ChevronLeft />
            </Button>
            <Button variant="outline" size="icon-sm" :disabled="page >= totalPages || loading" aria-label="Halaman berikutnya" @click="load(page + 1)">
              <ChevronRight />
            </Button>
          </div>
        </div>
      </Card>
    </div>
  </DashboardLayout>
</template>
