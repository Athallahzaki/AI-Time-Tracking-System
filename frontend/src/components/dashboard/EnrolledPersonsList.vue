<script setup>
import { ref, computed, onMounted } from 'vue';
import { RefreshCw, Search, Users, ShieldCheck, Clock } from '@lucide/vue';
import { useEnrollment } from '@/composables/useEnrollment';

const { enrolledPersons, isLoadingList, listError, fetchEnrolledPersons } =
  useEnrollment();

const searchQuery = ref('');

onMounted(fetchEnrolledPersons);

function formatDateTime(iso) {
  if (!iso) return '-';
  const date = new Date(iso);
  if (isNaN(date.getTime())) return '-';
  return date.toLocaleString('id-ID', {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
}

const filteredPersons = computed(() => {
  const q = searchQuery.value.trim().toLowerCase();
  if (!q) return enrolledPersons;
  return enrolledPersons.filter((p) =>
    p.person_id.toLowerCase().includes(q),
  );
});
</script>

<template>
  <div class="rounded-xl border border-slate-200 bg-white shadow-xs">
    <!-- Header -->
    <div class="flex flex-col gap-3 border-b border-slate-100 p-4 sm:flex-row sm:items-center sm:justify-between">
      <div class="flex items-center gap-2.5">
        <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
          <Users class="h-4 w-4" />
        </div>
        <div>
          <div class="flex items-center gap-2">
            <h3 class="text-base font-semibold text-slate-900">
              Daftar Karyawan Terdaftar
            </h3>
            <span class="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600">
              {{ enrolledPersons.length }}
            </span>
          </div>
          <p class="text-xs text-slate-500">
            Daftar profil identitas yang aktif digunakan oleh engine rekognisi.
          </p>
        </div>
      </div>

      <button
        class="inline-flex items-center gap-1.5 self-start rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900 disabled:opacity-50 sm:self-auto transition-colors"
        :disabled="isLoadingList"
        @click="fetchEnrolledPersons"
      >
        <RefreshCw class="h-3.5 w-3.5" :class="isLoadingList ? 'animate-spin text-indigo-600' : ''" />
        <span>{{ isLoadingList ? 'Menyinkronkan...' : 'Segarkan Data' }}</span>
      </button>
    </div>

    <!-- Search input -->
    <div class="border-b border-slate-100 bg-slate-50/50 px-4 py-2.5">
      <div class="relative max-w-sm">
        <Search class="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
        <input
          v-model="searchQuery"
          type="text"
          placeholder="Cari berdasarkan ID karyawan..."
          class="w-full rounded-md border border-slate-200 bg-white py-1.5 pl-8 pr-3 text-xs text-slate-800 placeholder-slate-400 focus:border-indigo-500 focus:outline-hidden focus:ring-1 focus:ring-indigo-500"
        />
      </div>
    </div>

    <!-- States: Loading, Error, Empty, List -->
    <div
      v-if="isLoadingList && enrolledPersons.length === 0"
      class="flex flex-col items-center justify-center px-4 py-12 text-slate-400"
    >
      <RefreshCw class="h-6 w-6 animate-spin text-indigo-500 mb-2" />
      <p class="text-xs">Memuat daftar karyawan dari server...</p>
    </div>

    <div
      v-else-if="listError"
      class="px-4 py-8 text-center text-xs text-red-600"
    >
      <p class="font-semibold">Gagal memuat data:</p>
      <p class="mt-0.5 text-slate-500">{{ listError }}</p>
      <button
        class="mt-2 text-xs font-medium text-indigo-600 underline hover:text-indigo-800"
        @click="fetchEnrolledPersons"
      >
        Coba lagi
      </button>
    </div>

    <div
      v-else-if="enrolledPersons.length === 0"
      class="px-4 py-12 text-center text-slate-400"
    >
      <Users class="mx-auto h-8 w-8 text-slate-300 mb-2" />
      <p class="text-sm font-medium text-slate-600">Belum ada karyawan terdaftar</p>
      <p class="mt-1 text-xs text-slate-400 max-w-xs mx-auto">
        Gunakan form di samping untuk mendaftarkan wajah karyawan pertama.
      </p>
    </div>

    <div
      v-else-if="filteredPersons.length === 0"
      class="px-4 py-8 text-center text-xs text-slate-400"
    >
      Tidak ada karyawan dengan ID cocok "{{ searchQuery }}".
    </div>

    <ul v-else class="divide-y divide-slate-100 max-h-[520px] overflow-y-auto">
      <li
        v-for="p in filteredPersons"
        :key="p.person_id"
        class="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between hover:bg-slate-50/80 transition-colors"
      >
        <div class="flex items-center gap-3">
          <div class="flex h-9 w-9 items-center justify-center rounded-full bg-slate-100 text-xs font-bold text-slate-700">
            {{ p.person_id.slice(0, 2).toUpperCase() }}
          </div>
          <div>
            <div class="flex items-center gap-2">
              <span class="text-sm font-semibold text-slate-900">{{ p.person_id }}</span>
              <span class="rounded bg-indigo-50 px-1.5 py-0.5 text-[10px] font-medium text-indigo-700">
                v{{ p.enrollment_version }}
              </span>
            </div>
            <p class="text-[11px] text-slate-500 flex items-center gap-1 mt-0.5">
              <ShieldCheck class="h-3 w-3 text-emerald-600 inline" />
              <span>{{ p.reference_count }} foto referensi valid</span>
            </p>
          </div>
        </div>

        <div class="text-[11px] text-slate-400 sm:text-right space-y-0.5 pl-12 sm:pl-0">
          <p class="flex items-center gap-1 sm:justify-end text-slate-600">
            <Clock class="h-3 w-3 text-slate-400" />
            <span>Terdaftar: {{ formatDateTime(p.enrolled_at) }}</span>
          </p>
          <p v-if="p.last_seen_at" class="text-slate-400">
            Terakhir terlihat: {{ formatDateTime(p.last_seen_at) }}
          </p>
        </div>
      </li>
    </ul>
  </div>
</template>
