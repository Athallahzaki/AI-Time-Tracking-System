<script setup>
import { reactive } from 'vue';
import { RouterLink } from 'vue-router';
import { AlertTriangle, ChevronDown, RefreshCw } from '@lucide/vue';
import { useEmployeeAllowance } from '@/composables/useEmployeeAllowance';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { Skeleton } from '@/components/ui/skeleton';

const { sortedUsages, isLoading, loadError, refetch, getEmployeeName } =
  useEmployeeAllowance();

const expandedIds = reactive(new Set());

function setExpanded(personId, open) {
  if (open) expandedIds.add(personId);
  else expandedIds.delete(personId);
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

// Warna dari status yang SUDAH DIHITUNG backend (services/free_time.py) —
// bukan ambang batas yang ditebak sendiri di frontend.
const STATUS_BAR_COLOR = {
  ok: 'bg-emerald-500',
  warning: 'bg-amber-500',
  exceeded: 'bg-red-500',
};
</script>

<template>
  <Card class="gap-0 py-0 shadow-xs">
    <div class="flex items-center justify-between border-b px-4 py-3">
      <h3 class="text-sm font-semibold text-slate-800">
        Jatah Free Time Karyawan
      </h3>
      <div class="flex items-center gap-1">
        <Button
          as-child
          variant="link"
          size="xs"
          class="text-indigo-600 hover:text-indigo-800"
        >
          <RouterLink to="/settings">Atur Kebijakan</RouterLink>
        </Button>
        <Button
          variant="ghost"
          size="xs"
          class="text-slate-500 hover:text-slate-700"
          :disabled="isLoading"
          @click="refetch"
        >
          <RefreshCw :class="isLoading && 'animate-spin'" />
          Refresh
        </Button>
      </div>
    </div>

    <div v-if="isLoading" class="space-y-3 px-4 py-4">
      <div v-for="n in 3" :key="n" class="flex items-center gap-3">
        <div class="flex-1 space-y-2">
          <Skeleton class="h-3.5 w-40" />
          <Skeleton class="h-1.5 w-full max-w-55" />
        </div>
        <Skeleton class="h-4 w-16" />
      </div>
    </div>

    <div v-else-if="loadError" class="p-4">
      <Alert variant="destructive" class="border-red-200 bg-red-50">
        <AlertTriangle />
        <AlertTitle class="line-clamp-none"
          >Gagal memuat: {{ loadError }}</AlertTitle
        >
        <AlertDescription
          >Periksa backend: GET /api/attendance/breaks</AlertDescription
        >
      </Alert>
    </div>

    <div
      v-else-if="sortedUsages.length === 0"
      class="px-4 py-6 text-center text-sm text-slate-400"
    >
      Belum ada pemakaian jatah free time hari ini.
    </div>

    <ul v-else class="divide-y">
      <Collapsible
        v-for="u in sortedUsages"
        :key="u.person_id"
        as="li"
        :open="expandedIds.has(u.person_id)"
        @update:open="(open) => setExpanded(u.person_id, open)"
      >
        <CollapsibleTrigger
          class="group flex w-full items-center gap-3 px-4 py-3 text-left outline-none hover:bg-slate-50 focus-visible:bg-slate-50"
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
              class="mt-1 flex items-center gap-1 text-[11px] text-amber-600"
            >
              <AlertTriangle class="h-3 w-3 shrink-0" />
              {{ u.suspicious_gap_count }} celah mencurigakan tidak dihitung —
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
              {{ u.break_count }} kunjungan
            </p>
          </div>
          <ChevronDown
            class="h-4 w-4 shrink-0 text-slate-400 transition-transform group-data-[state=open]:rotate-180"
          />
        </CollapsibleTrigger>

        <CollapsibleContent class="bg-slate-50/60 px-4 pb-3">
          <div v-if="u.breaks.length === 0" class="py-3 text-xs text-slate-400">
            Tidak ada kunjungan ke ruang fasilitas hari ini.
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
                  <Badge
                    variant="outline"
                    class="border-slate-200 bg-slate-50 text-[10px] text-slate-600"
                  >
                    {{
                      b.end_reason === 'open'
                        ? 'Sedang di ruangan'
                        : 'Kunjungan'
                    }}
                  </Badge>
                  <Badge
                    v-if="b.corrected"
                    variant="outline"
                    class="border-violet-200 bg-violet-50 text-[10px] text-violet-700"
                  >
                    Dikoreksi
                  </Badge>
                </div>
              </div>

              <p
                v-if="b.corrected && b.original_duration_seconds != null"
                class="mt-1.5 text-[11px] text-slate-400"
              >
                Dikecualikan. Durasi terhitung sebelum koreksi:
                {{ formatDurationShort(b.original_duration_seconds) }}
              </p>

              <div
                class="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-400"
              >
                <span
                  >Visit ID:
                  <strong class="text-slate-600">{{ b.gap_id }}</strong></span
                >
              </div>
            </li>
          </ul>
        </CollapsibleContent>
      </Collapsible>
    </ul>
  </Card>
</template>
