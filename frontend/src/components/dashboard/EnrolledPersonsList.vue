<script setup>
import { ref, computed, onMounted } from 'vue';
import { RefreshCw, Search, Users, ShieldCheck, Clock } from '@lucide/vue';
import { useEnrollment } from '@/composables/useEnrollment';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';

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
  <Card class="gap-0 py-0 shadow-xs">
    <!-- Header -->
    <div class="flex flex-col gap-3 border-b p-4 sm:flex-row sm:items-center sm:justify-between">
      <div class="flex items-center gap-2.5">
        <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
          <Users class="h-4 w-4" />
        </div>
        <div>
          <div class="flex items-center gap-2">
            <h3 class="text-base font-semibold text-slate-900">
              Daftar Karyawan Terdaftar
            </h3>
            <Badge variant="secondary" class="bg-slate-100 font-semibold text-slate-600">
              {{ enrolledPersons.length }}
            </Badge>
          </div>
          <p class="text-xs text-slate-500">
            Daftar profil identitas yang aktif digunakan oleh engine rekognisi.
          </p>
        </div>
      </div>

      <Button
        variant="outline"
        size="sm"
        class="h-8 self-start text-xs text-slate-600 sm:self-auto"
        :disabled="isLoadingList"
        @click="fetchEnrolledPersons"
      >
        <RefreshCw :class="isLoadingList ? 'animate-spin text-indigo-600' : ''" />
        {{ isLoadingList ? 'Menyinkronkan...' : 'Segarkan Data' }}
      </Button>
    </div>

    <!-- Search input -->
    <div class="border-b bg-slate-50/50 px-4 py-2.5">
      <div class="relative max-w-sm">
        <Search class="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
        <Input
          v-model="searchQuery"
          type="search"
          aria-label="Cari karyawan"
          placeholder="Cari berdasarkan ID karyawan..."
          class="h-8 bg-white pl-8 text-xs md:text-xs"
        />
      </div>
    </div>

    <!-- States: Loading, Error, Empty, List -->
    <div v-if="isLoadingList && enrolledPersons.length === 0" class="divide-y">
      <div v-for="n in 4" :key="n" class="flex items-center gap-3 px-4 py-3">
        <Skeleton class="h-9 w-9 rounded-full" />
        <div class="flex-1 space-y-2">
          <Skeleton class="h-3.5 w-32" />
          <Skeleton class="h-3 w-44" />
        </div>
      </div>
    </div>

    <div
      v-else-if="listError"
      class="px-4 py-8 text-center text-xs text-red-600"
    >
      <p class="font-semibold">Gagal memuat data:</p>
      <p class="mt-0.5 text-slate-500">{{ listError }}</p>
      <Button
        variant="link"
        size="xs"
        class="mt-1 text-indigo-600 hover:text-indigo-800"
        @click="fetchEnrolledPersons"
      >
        Coba lagi
      </Button>
    </div>

    <div
      v-else-if="enrolledPersons.length === 0"
      class="px-4 py-12 text-center text-slate-400"
    >
      <Users class="mx-auto mb-2 h-8 w-8 text-slate-300" />
      <p class="text-sm font-medium text-slate-600">Belum ada karyawan terdaftar</p>
      <p class="mx-auto mt-1 max-w-xs text-xs text-slate-400">
        Gunakan form di samping untuk mendaftarkan wajah karyawan pertama.
      </p>
    </div>

    <div
      v-else-if="filteredPersons.length === 0"
      class="px-4 py-8 text-center text-xs text-slate-400"
    >
      Tidak ada karyawan dengan ID cocok "{{ searchQuery }}".
    </div>

    <ul v-else class="max-h-[520px] divide-y overflow-y-auto">
      <li
        v-for="p in filteredPersons"
        :key="p.person_id"
        class="flex flex-col gap-2 px-4 py-3 transition-colors hover:bg-slate-50/80 sm:flex-row sm:items-center sm:justify-between"
      >
        <div class="flex items-center gap-3">
          <Avatar class="size-9">
            <AvatarFallback class="bg-slate-100 text-xs font-bold text-slate-700">
              {{ p.person_id.slice(0, 2).toUpperCase() }}
            </AvatarFallback>
          </Avatar>
          <div>
            <div class="flex items-center gap-2">
              <span class="text-sm font-semibold text-slate-900">{{ p.person_id }}</span>
              <Badge variant="secondary" class="rounded bg-indigo-50 px-1.5 text-[10px] text-indigo-700">
                v{{ p.enrollment_version }}
              </Badge>
            </div>
            <p class="mt-0.5 flex items-center gap-1 text-[11px] text-slate-500">
              <ShieldCheck class="inline h-3 w-3 text-emerald-600" />
              <span>{{ p.reference_count }} foto referensi valid</span>
            </p>
          </div>
        </div>

        <div class="space-y-0.5 pl-12 text-[11px] text-slate-400 sm:pl-0 sm:text-right">
          <p class="flex items-center gap-1 text-slate-600 sm:justify-end">
            <Clock class="h-3 w-3 text-slate-400" />
            <span>Terdaftar: {{ formatDateTime(p.enrolled_at) }}</span>
          </p>
          <p v-if="p.last_seen_at" class="text-slate-400">
            Terakhir terlihat: {{ formatDateTime(p.last_seen_at) }}
          </p>
        </div>
      </li>
    </ul>
  </Card>
</template>
