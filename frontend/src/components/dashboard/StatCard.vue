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
    class="rounded-xl border bg-white p-4"
    :class="variant === 'warning' && 'border-red-200 bg-red-50/40'"
  >
    <div class="flex items-center justify-between">
      <span class="text-sm text-slate-500">{{ label }}</span>
      <div
        class="flex h-8 w-8 items-center justify-center rounded-lg"
        :class="iconBg"
      >
        <component :is="icon" class="h-4 w-4" :class="iconColor" />
      </div>
    </div>

    <div class="mt-3 flex items-baseline gap-2">
      <span
        class="text-2xl font-semibold"
        :class="variant === 'warning' ? 'text-red-600' : 'text-slate-900'"
      >
        {{ value }}
      </span>
      <span v-if="suffix" class="text-sm font-medium text-slate-400">{{
        suffix
      }}</span>
      <span
        v-if="badge"
        class="ml-auto rounded-full bg-green-50 px-2 py-0.5 text-xs font-medium text-green-600"
      >
        {{ badge }}
      </span>
    </div>

    <p
      class="mt-1 text-xs"
      :class="variant === 'warning' ? 'text-red-500' : footnoteColor"
    >
      {{ footnote }}
    </p>
  </div>
</template>
