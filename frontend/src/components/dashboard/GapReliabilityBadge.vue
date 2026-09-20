<script setup>
defineProps({
  reliability: { type: String, required: true },
});
</script>

<template>
  <span
    class="inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium"
    :class="
      reliability === 'reliable'
        ? 'border-e-mist-200 bg-emerald-50 text-emerald-700'
        : 'border-dashed border-amber-300 bg-amber-50 text-amber-700'
    "
  >
    <span
      class="h-1.5 w-1.5 rounded-full"
      :class="reliability === 'reliable' ? 'bg-emerald-500' : 'bg-amber-500'"
    />
  </span>
</template>
