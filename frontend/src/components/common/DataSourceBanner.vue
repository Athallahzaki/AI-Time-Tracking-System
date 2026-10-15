<script setup>
import { computed } from 'vue';
import { FlaskConical } from '@lucide/vue';
import { apiSources, API_MODE } from '@/api/http';

// Menampilkan peringatan bila salah satu domain data di halaman ini sedang
// memakai data simulasi (endpoint backend belum ada). Supaya tidak ada yang
// mengira angka demo adalah angka sungguhan.
const props = defineProps({
  domains: { type: Array, required: true },
  note: { type: String, default: '' },
});

const mockDomains = computed(() => props.domains.filter((d) => apiSources[d] === 'mock'));
</script>

<template>
  <div
    v-if="mockDomains.length"
    class="flex items-start gap-2.5 rounded-lg border border-dashed border-violet-300 bg-violet-50/70 px-3.5 py-2.5 text-xs text-violet-900"
  >
    <FlaskConical class="mt-0.5 h-4 w-4 shrink-0 text-violet-600" />
    <div class="space-y-0.5">
      <p class="font-semibold">Data simulasi</p>
      <p class="text-violet-800/90">
        <template v-if="API_MODE === 'mock'">Frontend berjalan dalam mode mock (VITE_API_MODE=mock).</template>
        <template v-else>
          Endpoint backend untuk bagian ini belum tersedia, jadi data dibuat di browser.
          Begitu BE menyediakan endpoint-nya, halaman ini otomatis memakai data asli.
        </template>
        <span v-if="note"> {{ note }}</span>
      </p>
      <p class="font-mono text-[10px] text-violet-700/80">{{ mockDomains.join(', ') }}</p>
    </div>
  </div>
</template>
