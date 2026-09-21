<script setup>
import { reactive } from 'vue';
import { ChevronDown } from '@lucide/vue';
import { useEmployeeAllowance } from '@/composables/useEmployeeAllowance';
import GapClassificationBadge from './GapClassificationBadge.vue';

const { sortedUsages, isLoading, loadError, refetch, getEmployeeName } =
  useEmployeeAllowance();

const expandedIds = reactive(new Set());

function toggleExpanded(personId) {
  if (expandedIds.has(personId)) expandedIds.delete(personId);
  else expandedIds.add(personId);
}

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

function usagePct(u) {
  if (!u.allowance_minutes) return 0;
  return Math.min(
    100,
    Math.round((u.used_minutes / u.allowance_minutes) * 100),
  );
}

// Warna dari status yang SUDAH DIHITUNG backend (session_deriver.py / break_policy.py) —
// bukan ambang batas yang ditebak sendiri di frontend.
const STATUS_BAR_COLOR = {
  ok: 'bg-emerald-500',
  warning: 'bg-amber-500',
  exceeded: 'bg-red-500',
};
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
      <p class="mt-1 text-[11px] text-slate-400">
        (Endpoint GET /api/attendance/breaks mungkin belum tersedia di backend)
      </p>
    </div>

    <div
      v-else-if="sortedUsages.length === 0"
      class="px-4 py-6 text-center text-sm text-slate-400"
    >
      Belum ada data jatah istirahat hari ini.
    </div>

    <ul v-else class="divide-y">
      <li v-for="u in sortedUsages" :key="u.person_id">
        <button
          class="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-slate-50"
          @click="toggleExpanded(u.person_id)"
        >
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-medium text-slate-800">
              {{ getEmployeeName(u.person_id) }}
            </p>
            <div
              class="mt-1.5 h-1.5 w-full max-w-55 overflow-hidden rounded-full bg-slate-100"
            >
              <div
                class="h-full rounded-full transition-all"
                :class="STATUS_BAR_COLOR[u.status] || 'bg-slate-400'"
                :style="{ width: usagePct(u) + '%' }"
              />
            </div>
            <p
              v-if="u.suspicious_gap_count > 0"
              class="mt-1 text-[11px] text-amber-600"
            >
              ⚠ {{ u.suspicious_gap_count }} celah mencurigakan tidak dihitung —
              perlu ditinjau manual
            </p>
          </div>
          <div class="shrink-0 text-right">
            <p class="text-sm font-semibold text-slate-800">
              {{ u.remaining_minutes }}m
              <span class="font-normal text-slate-400"
                >/ {{ u.allowance_minutes }}m</span
              >
            </p>
            <p class="text-[11px] text-slate-400">
              {{ u.break_count }} istirahat
            </p>
          </div>
          <ChevronDown
            class="h-4 w-4 shrink-0 text-slate-400 transition-transform"
            :class="{ 'rotate-180': expandedIds.has(u.person_id) }"
          />
        </button>

        <div
          v-if="expandedIds.has(u.person_id)"
          class="bg-slate-50/60 px-4 pb-3"
        >
          <div v-if="u.breaks.length === 0" class="py-3 text-xs text-slate-400">
            Tidak ada istirahat tercatat hari ini.
          </div>
          <ul v-else class="space-y-2 pt-2">
            <li
              v-for="b in u.breaks"
              :key="b.gap_id"
              class="rounded-lg border bg-white p-2.5"
            >
              <div class="flex flex-wrap items-center justify-between gap-2">
                <div class="text-xs text-slate-600">
                  <span class="font-medium text-slate-800">{{
                    formatTimeRange(b.start_at, b.end_at)
                  }}</span>
                  <span class="text-slate-400">
                    · {{ formatDurationShort(b.duration_seconds) }}</span
                  >
                  <span class="text-slate-400"> · {{ b.camera_id }}</span>
                </div>
                <div class="flex items-center gap-1.5">
                  <GapClassificationBadge classification="break" />
                  <span
                    v-if="b.corrected"
                    class="rounded-full border border-violet-200 bg-violet-50 px-2 py-0.5 text-[10px] font-medium text-violet-700"
                  >
                    Dikoreksi
                  </span>
                </div>
              </div>

              <p
                v-if="b.corrected && b.original_duration_seconds != null"
                class="mt-1.5 text-[11px] text-slate-400"
              >
                Durasi asli sebelum koreksi:
                {{ formatDurationShort(b.original_duration_seconds) }}
              </p>

              <div
                class="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-400"
              >
                <span
                  >Keluar via:
                  <strong class="text-slate-600">{{ b.end_zone }}</strong></span
                >
                <span
                  >Alasan:
                  <strong class="text-slate-600">{{
                    b.end_reason
                  }}</strong></span
                >
              </div>
            </li>
          </ul>
        </div>
      </li>
    </ul>
  </div>
</template>
