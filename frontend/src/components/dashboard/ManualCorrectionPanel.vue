<script setup>
import { ref } from 'vue';
import ManualCorrectionForm from './ManualCorrectionForm.vue';
import CorrectionAuditLog from './CorrectionAuditLog.vue';

const showForm = ref(false);
const auditLogRef = ref(null);
const presetFields = ref({ sessionId: '', gapId: '' });

function openForm(preset = {}) {
  presetFields.value = {
    sessionId: preset.sessionId || '',
    gapId: preset.gapId || '',
  };
  showForm.value = true;
}

function handleSubmitted() {
  showForm.value = false;
  auditLogRef.value?.refetch();
}

// Dipanggil dari luar (mis. tombol "Koreksi" di BreakAllowancePanel) lewat template ref:
// manualCorrectionPanelRef.value.openForm({ gapId: b.gap_id })
defineExpose({ openForm });
</script>

<template>
  <div class="space-y-3">
    <div class="flex items-center justify-between">
      <h2 class="text-sm font-semibold text-slate-700">Koreksi Manual</h2>
      <button
        v-if="!showForm"
        class="rounded-md border px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
        @click="openForm()"
      >
        + Koreksi Baru
      </button>
    </div>

    <ManualCorrectionForm
      v-if="showForm"
      :preset-session-id="presetFields.sessionId"
      :preset-gap-id="presetFields.gapId"
      @submitted="handleSubmitted"
      @cancel="showForm = false"
    />

    <CorrectionAuditLog ref="auditLogRef" />
  </div>
</template>
