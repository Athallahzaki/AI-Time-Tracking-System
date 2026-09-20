<script setup>
defineProps({
  icon: { type: [Object, Function], required: true },
  iconBg: { type: String, default: 'bg-slate-100' },
  iconColor: { type: String, default: 'text-slate-500' },
  label: { type: String, required: true },
  value: { type: [String, Number], required: true },
  suffix: { type: String, default: '' },
  footnote: { type: String, default: '' },
  footnoteColor: { type: String, default: 'text-slate-400' },
  badge: { type: String, default: '' },
  variant: { type: String, default: 'default' },
});
</script>

<template>
  <div
    class="rounded-xl border bg-white p-3 sm:p-4 transition-all shadow-2xs"
    :class="variant === 'warning' && 'border-red-200 bg-red-50/40'"
  >
    <div class="flex items-center justify-between gap-2">
      <span class="text-xs sm:text-sm text-slate-500 font-medium truncate">{{ label }}</span>
      <div
        class="flex h-7 w-7 sm:h-8 sm:w-8 shrink-0 items-center justify-center rounded-lg"
        :class="iconBg"
      >
        <component :is="icon" class="h-3.5 w-3.5 sm:h-4 sm:w-4" :class="iconColor" />
      </div>
    </div>

    <div class="mt-2 sm:mt-3 flex items-baseline gap-1.5 sm:gap-2 flex-wrap">
      <span
        class="text-xl sm:text-2xl font-semibold tracking-tight"
        :class="variant === 'warning' ? 'text-red-600' : 'text-slate-900'"
      >
        {{ value }}
      </span>
      <span v-if="suffix" class="text-xs sm:text-sm font-medium text-slate-400">
        {{ suffix }}
      </span>
      <span
        v-if="badge"
        class="ml-auto rounded-full bg-green-50 px-1.5 sm:px-2 py-0.5 text-[10px] sm:text-xs font-medium text-green-600"
      >
        {{ badge }}
      </span>
    </div>

    <p
      class="mt-1 text-[11px] sm:text-xs truncate sm:whitespace-normal"
      :class="variant === 'warning' ? 'text-red-500' : footnoteColor"
      :title="footnote"
    >
      {{ footnote }}
    </p>
  </div>
</template>
