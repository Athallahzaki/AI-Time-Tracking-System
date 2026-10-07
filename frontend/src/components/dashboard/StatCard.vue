<script setup>
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';

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
  <Card
    class="gap-0 p-3 shadow-2xs transition-all sm:p-4"
    :class="variant === 'warning' && 'border-red-200 bg-red-50/40'"
  >
    <div class="flex items-center justify-between gap-2">
      <span class="truncate text-xs font-medium text-slate-500 sm:text-sm">{{
        label
      }}</span>
      <div
        class="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg sm:h-8 sm:w-8"
        :class="iconBg"
      >
        <component
          :is="icon"
          class="h-3.5 w-3.5 sm:h-4 sm:w-4"
          :class="iconColor"
        />
      </div>
    </div>

    <div class="mt-2 flex flex-wrap items-baseline gap-1.5 sm:mt-3 sm:gap-2">
      <span
        class="text-xl font-semibold tracking-tight sm:text-2xl"
        :class="variant === 'warning' ? 'text-red-600' : 'text-slate-900'"
      >
        {{ value }}
      </span>
      <span v-if="suffix" class="text-xs font-medium text-slate-400 sm:text-sm">
        {{ suffix }}
      </span>
      <Badge
        v-if="badge"
        variant="secondary"
        class="ml-auto bg-green-50 text-[10px] text-green-600 sm:text-xs"
      >
        {{ badge }}
      </Badge>
    </div>

    <p
      class="mt-1 truncate text-[11px] sm:text-xs sm:whitespace-normal"
      :class="variant === 'warning' ? 'text-red-500' : footnoteColor"
      :title="footnote"
    >
      {{ footnote }}
    </p>
  </Card>
</template>
