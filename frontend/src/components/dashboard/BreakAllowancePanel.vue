<script setup>
import { reactive, computed } from 'vue';
import { ChevronDown, Image as ImageIcon } from '@lucide/vue';
import GapReliabilityBadge from './GapReliabilityBadge.vue';
import {
  useEmployeeAllowance,
  classifyGapReliability,
} from '@/composables/useEmployeeAllowance';

const { employees, isLoading, loadError, refetch } = useEmployeeAllowance();

const expandedIds = reactive(new Set());
const expandedEvidence = reactive(new Set()); // key: interval_id

function toggleExpanded(personId) {
  if (expandedIds.has(personId)) expandedIds.delete(personId);
  else expandedIds.add(personId);
}

function toggleEvidence(intervalId) {
  if (expandedEvidence.has(intervalId)) expandedEvidence.delete(intervalId);
  else expandedEvidence.add(intervalId);
}

// Karyawan dengan sisa jatah paling sedikit ditaruh paling atas —
// itu yang paling butuh perhatian HR duluan.
const sortedEmployees = computed(() =>
  [...employees].sort((a, b) => a.remaining_minutes - b.remaining_minutes),
);

function formatTimeRange(startAt, endAt) {
  const fmt = (iso) =>
    new Date(iso).toLocaleTimeString('id-ID', {
      hour: '2-digit',
      minute: '2-digit',
    });
  return `${fmt(startAt)} – ${fmt(endAt)}`;
}

function formatDurationShort(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function usagePct(emp) {
  if (!emp.quota_minutes) return 0;
  return Math.min(
    100,
    Math.round((emp.used_minutes / emp.quota_minutes) * 100),
  );
}

// Asumsi path evidence crop di backend — sesuaikan kalau berbeda.
function evidenceUrl(filename) {
  return `/api/evidence/${filename}`;
}
</script>

<template>
  <div class="rounded-xl border bg-white shadow-xs">
    <div class="flex items-center justify-between border-b px-4 py-3">
      <h3 class="text-sm font-semibold text-slate-800">
        Jatah Istirahat Karyawan
      </h3>
      <button
        class="text-xs text-slate-500 hover:text-slate-700"
        @click="refetch"
      >
        Refresh
      </button>
    </div>

    <div v-if="isLoading" class="px-4 py-6 text-center text-sm text-slate-400">
      Memuat data...
    </div>

    <div
      v-else-if="loadError"
      class="px-4 py-6 text-center text-sm text-red-500"
    >
      Gagal memuat: {{ loadError }}
    </div>

    <div
      v-else-if="sortedEmployees.length === 0"
      class="px-4 py-6 text-center text-sm text-slate-400"
    >
      Belum ada data jatah istirahat.
    </div>

    <ul v-else class="divide-y">
      <li v-for="emp in sortedEmployees" :key="emp.person_id">
        <button
          class="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-slate-50"
          @click="toggleExpanded(emp.person_id)"
        >
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-medium text-slate-800">
              {{ emp.name }}
            </p>
            <div
              class="mt-1.5 h-1.5 w-full max-w-[220px] overflow-hidden rounded-full bg-slate-100"
            >
              <div
                class="h-full rounded-full transition-all"
                :class="
                  usagePct(emp) >= 100
                    ? 'bg-red-500'
                    : usagePct(emp) >= 70
                      ? 'bg-amber-500'
                      : 'bg-emerald-500'
                "
                :style="{ width: usagePct(emp) + '%' }"
              />
            </div>
          </div>
          <div class="shrink-0 text-right">
            <p class="text-sm font-semibold text-slate-800">
              {{ emp.remaining_minutes }}m
              <span class="font-normal text-slate-400"
                >/ {{ emp.quota_minutes }}m</span
              >
            </p>
            <p class="text-[11px] text-slate-400">
              {{ emp.gaps.length }} celah
            </p>
          </div>
          <ChevronDown
            class="h-4 w-4 shrink-0 text-slate-400 transition-transform"
            :class="{ 'rotate-180': expandedIds.has(emp.person_id) }"
          />
        </button>

        <div
          v-if="expandedIds.has(emp.person_id)"
          class="bg-slate-50/60 px-4 pb-3"
        >
          <div v-if="emp.gaps.length === 0" class="py-3 text-xs text-slate-400">
            Tidak ada celah tercatat hari ini.
          </div>
          <ul v-else class="space-y-2 pt-2">
            <li
              v-for="gap in emp.gaps"
              :key="gap.interval_id"
              class="rounded-lg border bg-white p-2.5"
            >
              <div class="flex flex-wrap items-center justify-between gap-2">
                <div class="text-xs text-slate-600">
                  <span class="font-medium text-slate-800">{{
                    formatTimeRange(gap.start_at, gap.end_at)
                  }}</span>
                  <span class="text-slate-400">
                    · {{ formatDurationShort(gap.duration_seconds) }}</span
                  >
                  <span class="text-slate-400"> · {{ gap.camera_id }}</span>
                </div>
                <GapReliabilityBadge
                  :reliability="classifyGapReliability(gap)"
                />
              </div>

              <div
                class="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-400"
              >
                <span
                  >Keluar via:
                  <strong class="text-slate-600">{{
                    gap.end_zone
                  }}</strong></span
                >
                <span
                  >Sumber:
                  <strong class="text-slate-600">{{
                    gap.end_source
                  }}</strong></span
                >
                <span
                  >Alasan:
                  <strong class="text-slate-600">{{
                    gap.end_reason
                  }}</strong></span
                >
              </div>

              <button
                v-if="gap.evidence_crop?.start || gap.evidence_crop?.end"
                class="mt-1.5 flex items-center gap-1 text-[11px] font-medium text-sky-600 hover:text-sky-700"
                @click="toggleEvidence(gap.interval_id)"
              >
                <ImageIcon class="h-3 w-3" />
                {{
                  expandedEvidence.has(gap.interval_id)
                    ? 'Sembunyikan bukti'
                    : 'Lihat bukti'
                }}
              </button>

              <div
                v-if="expandedEvidence.has(gap.interval_id)"
                class="mt-2 flex gap-2"
              >
                <div v-if="gap.evidence_crop?.start" class="text-center">
                  <img
                    :src="evidenceUrl(gap.evidence_crop.start)"
                    class="h-20 w-20 rounded border object-cover"
                    alt="Crop sesaat sebelum celah dimulai"
                  />
                  <p class="mt-0.5 text-[10px] text-slate-400">Sebelum celah</p>
                </div>
                <div v-if="gap.evidence_crop?.end" class="text-center">
                  <img
                    :src="evidenceUrl(gap.evidence_crop.end)"
                    class="h-20 w-20 rounded border object-cover"
                    alt="Crop saat celah berakhir"
                  />
                  <p class="mt-0.5 text-[10px] text-slate-400">Setelah celah</p>
                </div>
              </div>
            </li>
          </ul>
        </div>
      </li>
    </ul>
  </div>
</template>
