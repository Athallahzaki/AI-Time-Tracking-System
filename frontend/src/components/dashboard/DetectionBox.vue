<script setup>
import { computed } from 'vue';
import { identitySourceMeta } from '@/lib/format';
import { useOverlaySettings } from '@/composables/useOverlaySettings';

const { showIdentityStatus } = useOverlaySettings();

const isIdentificationStatus = computed(() =>
  /^(VERIFYING|IDENTIFYING)$/i.test(
    String(props.detection.sub ?? '').trim(),
  ),
);

const visibleConf = computed(() =>
  showIdentityStatus.value ? props.detection.conf : '',
);

const visibleSub = computed(() => {
  if (
    !showIdentityStatus.value &&
    isIdentificationStatus.value
  ) {
    return '';
  }

  return props.detection.sub;
});

const props = defineProps({
  detection: { type: Object, required: true },
  compact: { type: Boolean, default: false },
});

const colors = {
  emerald: '#6ee7b7',
  amber: '#facc15',
  red: '#f87171',
  cyan: '#67e8f9',
};

const boxColor = computed(
  () => colors[props.detection.color] || colors.emerald,
);

const source = computed(() =>
  identitySourceMeta(props.detection.identitySource),
);

const isReid = computed(() =>
  ['reid', 'reid_retro'].includes(
    props.detection.identitySource,
  ),
);

const extraText = computed(() => {
  const detection = props.detection;

  // Hapus prefix lama supaya VERIFYING tidak muncul dua kali.
  const extra = String(detection.extra ?? '')
    .replace(
      /^(VERIFYING|IDENTIFYING)\b[\s·:–—-]*/i,
      '',
    )
    .trim();

  const qualifying =
    detection.timerMode === 'qualifying' ||
    isIdentificationStatus.value;

  if (!showIdentityStatus.value || !qualifying || !extra) {
    return extra;
  }

  const status = isIdentificationStatus.value
    ? String(detection.sub).toUpperCase()
    : 'VERIFYING';

  return `${status} · ${extra}`;
});

// Koordinat detection menggunakan persentase area video.
// Label masuk ke kotak saat berada dekat tepi atas/bawah.
// Dekat tepi kanan, label diratakan ke kanan.
const labelPlacement = computed(() => {
  const top = Number.parseFloat(props.detection.top) || 0;
  const left = Number.parseFloat(props.detection.left) || 0;
  const height = Number.parseFloat(props.detection.height) || 0;
  const width = Number.parseFloat(props.detection.width) || 0;

  return {
    topInside: top < 8,
    bottomInside: top + height > 92,
    alignRight: left + width / 2 > 65,
  };
});
</script>

<template>
  <div
    class="detection-box"
    :class="{
      compact,
      warning: detection.warning,
      'top-inside': labelPlacement.topInside,
      'bottom-inside': labelPlacement.bottomInside,
      'align-right': labelPlacement.alignRight,
    }"
    :style="{
      top: detection.top,
      left: detection.left,
      width: detection.width,
      height: detection.height,
      '--box-color': boxColor,
    }"
  >
    <!-- Garis penghubung putus-putus. -->
    <div class="outline"></div>

    <!-- Empat sudut tebal. -->
    <span class="corner top-left"></span>
    <span class="corner top-right"></span>
    <span class="corner bottom-left"></span>
    <span class="corner bottom-right"></span>

    <span class="mid-tick tick-left"></span>
    <span class="mid-tick tick-right"></span>
    <span class="mid-tick tick-top"></span>
    <span class="mid-tick tick-bottom"></span>
    <!-- Status, confidence, dan sumber identitas. -->
    <div
        v-if="visibleSub || visibleConf || source"
        class="top-label"
      >
        <span v-if="visibleSub">
          {{ visibleSub }}
        </span>

        <span v-if="visibleConf">
          {{ visibleSub ? ' · ' : '' }}{{ visibleConf }}
        </span>

        <span
          v-if="source"
          class="source"
          :class="{ reid: isReid }"
          :title="source.hint"
        >
          {{ source.short }}
        </span>
      </div>

    <!-- Timer / informasi tambahan. -->
    <div
        v-if="showIdentityStatus && extraText"
        class="bottom-label">
        {{ extraText }}
      </div>
  </div>
</template>

<style scoped>
.detection-box {
  position: absolute;
  pointer-events: none;
  box-sizing: border-box;
  overflow: visible;
  color: var(--box-color);

  --corner-size: 20px;
  --corner-thickness: 4px;
  --outline-thickness: 3px;
  --label-gap: 5px;
  --label-inset: 6px;
}

/* Garis putus-putus dibuat lebih tebal dan jelas. */
.outline {
  position: absolute;
  inset: 0;
  box-sizing: border-box;
  border: var(--outline-thickness) dashed currentColor;
  border-radius: 5px;
  opacity: 0.65;
}

.corner {
  position: absolute;
  box-sizing: border-box;
  width: min(var(--corner-size), 35%);
  height: min(var(--corner-size), 35%);
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

.top-label,
.bottom-label {
  position: absolute;
  left: 0;
  right: auto;
  z-index: 10;
  box-sizing: border-box;
  width: max-content;
  max-width: none;
  padding: 3px 5px;
  border-radius: 3px;
  background: rgb(2 6 23 / 75%);
  color: #fff;
  font-family: ui-monospace, monospace;
  font-size: 11px;
  font-weight: 500;
  line-height: 1.4;
  white-space: nowrap;
}

/* Normal: status berada di atas kotak. */
.top-label {
  top: auto;
  bottom: 100%;
  margin: 0 0 var(--label-gap);
}

/* Normal: timer berada di bawah kotak. */
.bottom-label {
  top: 100%;
  bottom: auto;
  margin: var(--label-gap) 0 0;
}

/* Dekat tepi kanan: label melebar ke kiri. */
.align-right .top-label,
.align-right .bottom-label {
  left: auto;
  right: 0;
}

/* Dekat tepi atas: status masuk ke dalam kotak. */
.top-inside .top-label {
  top: var(--label-inset);
  bottom: auto;
  left: var(--label-inset);
  margin: 0;
}

/* Dekat tepi bawah: timer masuk ke dalam kotak. */
.bottom-inside .bottom-label {
  top: auto;
  bottom: var(--label-inset);
  left: var(--label-inset);
  margin: 0;
}

.align-right.top-inside .top-label,
.align-right.bottom-inside .bottom-label {
  left: auto;
  right: var(--label-inset);
}

.source {
  display: inline-block;
  margin-left: 4px;
  padding: 0 3px;
  border-radius: 2px;
  background: rgb(255 255 255 / 15%);
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
}

.source.reid {
  background: rgb(139 92 246 / 85%);
  color: #fff;
}

.warning .top-label,
.warning .bottom-label {
  background: rgb(127 29 29 / 90%);
}

/* Ukuran lebih kecil untuk tampilan grid. */
.compact {
  --corner-size: 14px;
  --corner-thickness: 3px;
  --outline-thickness: 2px;
  --label-gap: 4px;
  --label-inset: 5px;
}

.compact .top-label,
.compact .bottom-label {
  padding: 2px 4px;
  font-size: 9px;
}

.compact .source {
  font-size: 8px;
}

.mid-tick {
  position: absolute;
  background: currentColor;
  opacity: 0.85;
  border-radius: 1px;
}

/* Tengah kiri: garis masuk ke kanan. */
.tick-left {
  left: 0;
  top: 50%;
  width: min(16px, 20%);
  height: 3px;
  transform: translateY(-50%);
}

/* Tengah kanan: garis masuk ke kiri. */
.tick-right {
  right: 0;
  top: 50%;
  width: min(16px, 20%);
  height: 3px;
  transform: translateY(-50%);
}

/* Tengah atas: garis masuk ke bawah. */
.tick-top {
  top: 0;
  left: 50%;
  width: 3px;
  height: min(16px, 20%);
  transform: translateX(-50%);
}

/* Tengah bawah: garis masuk ke atas. */
.tick-bottom {
  bottom: 0;
  left: 50%;
  width: 3px;
  height: min(16px, 20%);
  transform: translateX(-50%);
}

/* Ukuran lebih kecil untuk grid. */
.compact .tick-left,
.compact .tick-right {
  width: min(11px, 20%);
  height: 2px;
}

.compact .tick-top,
.compact .tick-bottom {
  width: 2px;
  height: min(11px, 20%);
}
</style>