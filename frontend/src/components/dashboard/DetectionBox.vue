<script setup>
import { computed } from 'vue';

const props = defineProps({
  detection: { type: Object, required: true },
  compact: { type: Boolean, default: false },
});

const colors = {
  emerald: '#6ee7b7',
  amber: '#facc15',
  red: '#f87171',
  cyan: '#e2e8f0',
};

const boxColor = computed(() =>
  props.detection.warning
    ? colors.red
    : colors[props.detection.color] || colors.cyan,
);

const label = computed(() => {
  const detection = props.detection;

  return detection.label ||
    (detection.track_id != null
      ? `ID ${detection.track_id}`
      : '');
});

const identitySource = computed(() => {
  const source = props.detection.identitySource;

  if (source === 'reid' || source === 'reid_retro') {
    return 'ReID';
  }

  return '';
});
</script>

<template>
  <div
    class="detection-box"
    :class="{ compact }"
    :style="{
      top: detection.top,
      left: detection.left,
      width: detection.width,
      height: detection.height,
      '--box-color': boxColor,
    }"
  >
    <!-- Garis tipis yang menghubungkan empat sudut. -->
    <div class="outline"></div>

    <!-- Sudut tebal seperti referensi. -->
    <span class="corner top-left"></span>
    <span class="corner top-right"></span>
    <span class="corner bottom-left"></span>
    <span class="corner bottom-right"></span>

    <!-- Nama / ID kecil di dalam kotak. -->
    <div v-if="label" class="identity">
      <span>{{ label }}</span>
      <span v-if="identitySource" class="source">
        {{ identitySource }}
      </span>
    </div>

    <!-- Timer tetap terlihat tanpa badge besar. -->
    <div v-if="detection.extra" class="timer">
      {{ detection.extra }}
    </div>
  </div>
</template>

<style scoped>
.detection-box {
  position: absolute;
  pointer-events: none;
  color: var(--box-color);
  box-sizing: border-box;
  --corner-size: 18px;
  --corner-thickness: 3px;
}

.outline {
  position: absolute;
  inset: 0;
  border: 1px dashed currentColor;
  border-radius: 5px;
  opacity: 0.35;
}

.corner {
  position: absolute;
  width: min(var(--corner-size), 35%);
  height: min(var(--corner-size), 35%);
  box-sizing: border-box;
  border: 0 solid currentColor;
}

.top-left {
  top: 0;
  left: 0;
  border-top-width: var(--corner-thickness);
  border-left-width: var(--corner-thickness);
  border-top-left-radius: 5px;
}

.top-right {
  top: 0;
  right: 0;
  border-top-width: var(--corner-thickness);
  border-right-width: var(--corner-thickness);
  border-top-right-radius: 5px;
}

.bottom-left {
  bottom: 0;
  left: 0;
  border-bottom-width: var(--corner-thickness);
  border-left-width: var(--corner-thickness);
  border-bottom-left-radius: 5px;
}

.bottom-right {
  bottom: 0;
  right: 0;
  border-bottom-width: var(--corner-thickness);
  border-right-width: var(--corner-thickness);
  border-bottom-right-radius: 5px;
}

.identity,
.timer {
  position: absolute;
  left: 6px;
  right: 6px;
  width: fit-content;
  max-width: calc(100% - 12px);
  padding: 2px 4px;
  border-radius: 3px;
  background: rgb(0 0 0 / 45%);
  color: #fff;
  font-family: ui-monospace, monospace;
  font-size: 10px;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.identity {
  top: 6px;
}

.timer {
  bottom: 6px;
}

.source {
  margin-left: 5px;
  color: #c4b5fd;
  font-size: 9px;
}

.compact {
  --corner-size: 12px;
  --corner-thickness: 2px;
}

.compact .identity,
.compact .timer {
  font-size: 9px;
}
</style>