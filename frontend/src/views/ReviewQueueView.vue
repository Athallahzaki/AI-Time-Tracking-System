<script setup>
import { computed, onMounted, ref } from 'vue';
import { CheckCircle2, ClipboardCheck, Info, RefreshCw, XCircle } from '@lucide/vue';
import DashboardLayout from '@/layouts/DashboardLayout.vue';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { tableClass } from '@/components/ui/table';
import DataSourceBanner from '@/components/common/DataSourceBanner.vue';
import VisitTimeline from '@/components/reports/VisitTimeline.vue';
import { decideReview, getReview, listReviews } from '@/api/reviews';
import { formatDate, formatDateTime, formatDuration } from '@/lib/format';

// Antrean tinjauan HR (dok. 12 §3.6 butir 6): pelanggaran yang sebagian besar
// menitnya bersumber ReID (bukan wajah) ditandai "perlu dicek HR". Sistem hanya
// memberi tanda — keputusan tetap di HR (dok. 12 §1).
const status = ref('pending');
const items = ref([]);
const loading = ref(false);
const error = ref('');

const detailOpen = ref(false);
const detail = ref(null);
const detailLoading = ref(false);
const detailError = ref('');
const note = ref('');
const deciding = ref('');
const decideError = ref('');

const reidShare = (item) => (item.used_seconds ? Math.round((item.reid_seconds / item.used_seconds) * 100) : 0);
const pendingCount = computed(() => (status.value === 'pending' ? items.value.length : null));

async function load() {
  loading.value = true;
  error.value = '';
  try {
    items.value = await listReviews({ status: status.value });
  } catch (err) {
    error.value = err?.message || 'Gagal memuat antrean tinjauan.';
  } finally {
    loading.value = false;
  }
}
onMounted(load);

function onStatusChange(value) {
  status.value = value;
  load();
}

async function openDetail(item) {
  detailOpen.value = true;
  detail.value = { ...item, segments: [] };
  detailLoading.value = true;
  detailError.value = '';
  decideError.value = '';
  note.value = item.note || '';
  try {
    detail.value = await getReview(item.id);
  } catch (err) {
    detailError.value = err?.message || 'Gagal memuat rincian.';
  } finally {
    detailLoading.value = false;
  }
}

async function decide(decision) {
  if (decision === 'reject' && !note.value.trim()) {
    decideError.value = 'Tulis alasan penolakan (mis. "bukan orang ini, rekaman menunjukkan …").';
    return;
  }
  deciding.value = decision;
  decideError.value = '';
  try {
    const updated = await decideReview(detail.value.id, decision, note.value.trim());
    detail.value = { ...detail.value, ...updated };
    if (status.value === 'pending') items.value = items.value.filter((i) => i.id !== updated.id);
    else items.value = items.value.map((i) => (i.id === updated.id ? updated : i));
    detailOpen.value = false;
  } catch (err) {
    decideError.value = err?.message || 'Gagal menyimpan keputusan.';
  } finally {
    deciding.value = '';
  }
}

const STATUS_LABEL = { pending: 'Menunggu', confirmed: 'Dikonfirmasi', rejected: 'Ditolak' };
const STATUS_CLASS = {
  pending: 'bg-amber-50 text-amber-700',
  confirmed: 'bg-red-50 text-red-700',
  rejected: 'bg-slate-100 text-slate-600',
};
</script>

<template>
  <DashboardLayout :crumbs="['Laporan', 'Tinjauan HR']">
    <div class="mx-auto max-w-6xl space-y-5">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 class="flex items-center gap-2 text-2xl font-bold tracking-tight text-slate-900">
            <ClipboardCheck class="h-6 w-6 text-amber-600" />
            Antrean Tinjauan HR
          </h1>
          <p class="mt-1 text-sm text-slate-500">
            Pelanggaran yang sebagian besar waktunya disambung lewat ReID (penampilan tubuh), bukan wajah.
          </p>
        </div>
        <Button variant="outline" size="sm" :disabled="loading" @click="load">
          <RefreshCw :class="loading && 'animate-spin'" />
          Muat ulang
        </Button>
      </div>

      <DataSourceBanner :domains="['reviews', 'employees']" />

      <div class="flex items-start gap-2 rounded-lg border bg-white px-3.5 py-2.5 text-xs text-slate-600">
        <Info class="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
        <p>
          Pelanggaran di antrean ini <b>belum diverifikasi</b>. Konfirmasi bila rekaman/kunjungan memang orang ini;
          tolak bila salah sambung — penolakan dicatat dan jatahnya dikoreksi lewat Koreksi Manual di dashboard.
        </p>
      </div>

      <Tabs :model-value="status" @update:model-value="onStatusChange">
        <TabsList>
          <TabsTrigger value="pending">Menunggu<span v-if="pendingCount !== null" class="ml-1 text-xs opacity-70">({{ pendingCount }})</span></TabsTrigger>
          <TabsTrigger value="confirmed">Dikonfirmasi</TabsTrigger>
          <TabsTrigger value="rejected">Ditolak</TabsTrigger>
          <TabsTrigger value="all">Semua</TabsTrigger>
        </TabsList>
      </Tabs>

      <p v-if="error" class="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{{ error }}</p>

      <Card class="gap-0 py-0 shadow-xs">
        <div :class="tableClass.wrapper">
          <table :class="tableClass.table">
            <thead :class="tableClass.thead">
              <tr>
                <th :class="tableClass.th">Tanggal</th>
                <th :class="tableClass.th">Karyawan</th>
                <th :class="tableClass.th">Terpakai</th>
                <th :class="tableClass.th">Porsi ReID</th>
                <th :class="tableClass.th" class="hidden sm:table-cell">Kunjungan</th>
                <th :class="tableClass.th">Status</th>
                <th :class="tableClass.th"><span class="sr-only">Aksi</span></th>
              </tr>
            </thead>
            <tbody :class="tableClass.tbody">
              <tr v-if="loading && !items.length">
                <td colspan="7" class="px-3 py-10 text-center text-sm text-slate-400">Memuat…</td>
              </tr>
              <tr v-else-if="!items.length">
                <td colspan="7" class="px-3 py-10 text-center text-sm text-slate-400">
                  {{ status === 'pending' ? 'Tidak ada yang perlu ditinjau. ' : '' }}Antrean kosong.
                </td>
              </tr>
              <tr v-for="item in items" :key="item.id" :class="[tableClass.tr, 'cursor-pointer']" @click="openDetail(item)">
                <td :class="tableClass.td" class="text-xs whitespace-nowrap text-slate-600">{{ formatDate(item.date) }}</td>
                <td :class="tableClass.td">
                  <p class="font-medium text-slate-900">{{ item.name }}</p>
                  <p class="font-mono text-[11px] text-slate-400">{{ item.employee_id }}</p>
                </td>
                <td :class="tableClass.td">
                  <span class="font-semibold text-red-600 tabular-nums">{{ formatDuration(item.used_seconds) }}</span>
                  <span class="text-xs text-slate-400"> / {{ formatDuration(item.allowance_seconds) }}</span>
                </td>
                <td :class="tableClass.td">
                  <div class="flex items-center gap-2">
                    <div class="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100">
                      <div class="h-full rounded-full bg-violet-500" :style="{ width: `${reidShare(item)}%` }" />
                    </div>
                    <span class="text-xs font-semibold text-violet-700">{{ reidShare(item) }}%</span>
                  </div>
                </td>
                <td :class="tableClass.td" class="hidden text-slate-600 sm:table-cell">{{ item.visits }}</td>
                <td :class="tableClass.td">
                  <span class="rounded-full px-2 py-0.5 text-[11px] font-semibold" :class="STATUS_CLASS[item.status]">
                    {{ STATUS_LABEL[item.status] || item.status }}
                  </span>
                </td>
                <td :class="tableClass.td" class="text-right">
                  <Button variant="outline" size="xs" @click.stop="openDetail(item)">Tinjau</Button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>
    </div>

    <Sheet v-model:open="detailOpen">
      <SheetContent class="w-full overflow-y-auto sm:max-w-lg">
        <div v-if="detail" class="space-y-5 p-5">
          <div>
            <SheetTitle class="text-lg">{{ detail.name }}</SheetTitle>
            <SheetDescription>
              <span class="font-mono">{{ detail.employee_id }}</span> · {{ formatDate(detail.date) }}
            </SheetDescription>
          </div>

          <div class="grid grid-cols-3 gap-2 text-center">
            <div class="rounded-lg bg-slate-50 px-2 py-2.5">
              <p class="text-[11px] text-slate-500">Terpakai</p>
              <p class="font-semibold text-red-600">{{ formatDuration(detail.used_seconds) }}</p>
            </div>
            <div class="rounded-lg bg-slate-50 px-2 py-2.5">
              <p class="text-[11px] text-slate-500">Dari ReID</p>
              <p class="font-semibold text-violet-700">{{ formatDuration(detail.reid_seconds) }}</p>
            </div>
            <div class="rounded-lg bg-slate-50 px-2 py-2.5">
              <p class="text-[11px] text-slate-500">Porsi ReID</p>
              <p class="font-semibold text-violet-700">{{ reidShare(detail) }}%</p>
            </div>
          </div>

          <div>
            <p class="mb-2 text-xs font-semibold text-slate-600">Linimasa kunjungan</p>
            <VisitTimeline :segments="detail.segments || []" :loading="detailLoading" :error="detailError" />
          </div>

          <div v-if="detail.status !== 'pending'" class="rounded-lg border px-3 py-2.5 text-xs text-slate-600">
            <b>{{ STATUS_LABEL[detail.status] }}</b> oleh {{ detail.decided_by || '-' }} · {{ formatDateTime(detail.decided_at) }}
            <p v-if="detail.note" class="mt-1 text-slate-500">"{{ detail.note }}"</p>
          </div>

          <div class="space-y-1.5">
            <Label for="review-note" class="text-xs font-semibold text-slate-700">Catatan HR</Label>
            <Textarea id="review-note" v-model="note" rows="3" placeholder="Alasan keputusan (wajib bila menolak)" />
          </div>
          <p v-if="decideError" class="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{{ decideError }}</p>

          <div class="flex flex-col gap-2 sm:flex-row">
            <Button class="flex-1 bg-red-600 hover:bg-red-700" :disabled="!!deciding" @click="decide('confirm')">
              <CheckCircle2 />
              {{ deciding === 'confirm' ? 'Menyimpan…' : 'Konfirmasi pelanggaran' }}
            </Button>
            <Button variant="outline" class="flex-1" :disabled="!!deciding" @click="decide('reject')">
              <XCircle />
              {{ deciding === 'reject' ? 'Menyimpan…' : 'Tolak (salah sambung)' }}
            </Button>
          </div>
          <p class="text-[11px] text-slate-400">
            Menolak hanya mencatat keputusan. Untuk mengembalikan jatah karyawan, buat Koreksi Manual
            (alasan "Salah orang") di dashboard.
          </p>
        </div>
      </SheetContent>
    </Sheet>
  </DashboardLayout>
</template>
