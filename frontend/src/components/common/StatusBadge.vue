<script setup>
import { computed } from 'vue';
import { STATUS_META } from '@/lib/format';

const props = defineProps({
  status: { type: String, required: true },
});

const meta = computed(
  () => STATUS_META[props.status] || { label: props.status, class: 'bg-slate-50 text-slate-600 border-slate-200' },
);
</script>

<template>
  <span
    class="inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap"
    :class="meta.class"
  >
    {{ meta.label }}
  </span>
</template>
