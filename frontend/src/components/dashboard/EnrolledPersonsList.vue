<script setup>
import { onMounted } from 'vue';
import { useEnrollment } from '@/composables/useEnrollment';

const { enrolledPersons, isLoadingList, listError, fetchEnrolledPersons } =
  useEnrollment();

onMounted(fetchEnrolledPersons);

function formatDateTime(iso) {
  if (!iso) return '-';
  return new Date(iso).toLocaleString('id-ID', {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
}
</script>

<template>
  <div class="rounded-xl border bg-white shadow-xs">
    <div class="flex items-center justify-between border-b px-4 py-3">
      <h3 class="text-sm font-semibold text-slate-800">Karyawan Terdaftar</h3>
      <button
        class="text-xs text-slate-500 hover:text-slate-700"
        @click="fetchEnrolledPersons"
      >
        Refresh
      </button>
    </div>

    <div
      v-if="isLoadingList"
      class="px-4 py-6 text-center text-sm text-slate-400"
    >
      Memuat...
    </div>
    <div
      v-else-if="listError"
      class="px-4 py-6 text-center text-sm text-red-500"
    >
      Gagal memuat: {{ listError }}
    </div>
    <div
      v-else-if="enrolledPersons.length === 0"
      class="px-4 py-6 text-center text-sm text-slate-400"
    >
      Belum ada karyawan terdaftar.
    </div>

    <ul v-else class="divide-y">
      <li
        v-for="p in enrolledPersons"
        :key="p.person_id"
        class="flex items-center justify-between px-4 py-3"
      >
        <div>
          <p class="text-sm font-medium text-slate-800">{{ p.person_id }}</p>
          <p class="text-[11px] text-slate-400">
            v{{ p.enrollment_version }} · {{ p.reference_count }} referensi
          </p>
        </div>
        <div class="text-right text-[11px] text-slate-400">
          <p>Didaftarkan: {{ formatDateTime(p.enrolled_at) }}</p>
          <p>Terakhir terlihat: {{ formatDateTime(p.last_seen_at) }}</p>
        </div>
      </li>
    </ul>
  </div>
</template>
