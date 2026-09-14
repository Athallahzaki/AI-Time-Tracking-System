<script setup>
defineProps({
  detection: { type: Object, required: true },
});

const colorMap = {
  emerald: 'border-emerald-400 text-emerald-300',
  amber: 'border-amber-400 text-amber-300',
  red: 'border-red-400 text-red-300',
};
</script>

<template>
  <div
    class="absolute rounded-md border-2"
    :class="colorMap[detection.color] || colorMap.emerald"
    :style="{
      top: detection.top,
      left: detection.left,
      width: detection.width,
      height: detection.height,
    }"
  >
    <div
      class="absolute -top-6 left-0 whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-medium"
      :class="
        detection.warning
          ? 'bg-red-500/90 text-white'
          : 'bg-black/70 text-white'
      "
    >
      {{ detection.label }} · {{ detection.sub }} · {{ detection.conf }}
    </div>
    <div
      v-if="detection.extra"
      class="absolute -bottom-6 left-0 whitespace-nowrap rounded px-1.5 py-0.5 text-[10px] font-medium"
      :class="
        detection.warning
          ? 'bg-red-500/90 text-white'
          : 'bg-black/70 text-white'
      "
    >
      {{ detection.extra }}
    </div>
  </div>
</template>
