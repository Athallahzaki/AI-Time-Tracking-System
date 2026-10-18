<script setup lang="ts">
import { onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { CalendarClock, Clock, Cpu, History, Mail, RefreshCw } from '@lucide/vue';
import DashboardLayout from '@/layouts/DashboardLayout.vue';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import DataSourceBanner from '@/components/common/DataSourceBanner.vue';
import AllowanceTab from '@/components/settings/AllowanceTab.vue';
import BreakHoursTab from '@/components/settings/BreakHoursTab.vue';
import EngineScheduleTab from '@/components/settings/EngineScheduleTab.vue';
import EmailTab from '@/components/settings/EmailTab.vue';
import SettingsAuditLog from '@/components/settings/SettingsAuditLog.vue';
import { useSettings } from '@/composables/useSettings';

import { useOverlaySettings } from '@/composables/useOverlaySettings';

const {
  showIdentityStatus,
  toggleIdentityStatus,
} = useOverlaySettings();

// Pengaturan dari web (dok. 12 §3.3), dipecah per tab. Tab aktif disimpan di
// ?tab= supaya bisa ditautkan langsung dan bertahan saat refresh.
const TABS = ['allowance', 'break-hours', 'engine', 'email', 'history'] as const;

const route = useRoute();
const router = useRouter();
const initial = String(route.query.tab || 'allowance');
const tab = ref<string>((TABS as readonly string[]).includes(initial) ? initial : 'allowance');

watch(tab, (value) => {
  router.replace({ query: { ...route.query, tab: value } });
});

const {
  policy,
  emailStatus,
  isLoading,
  isSaving,
  isSendingTestEmail,
  error,
  successMessage,
  fetchPolicy,
  updatePolicy,
  fetchEmailStatus,
  sendTestEmail,
} = useSettings();

const auditRef = ref<{ reload: () => void } | null>(null);
const reloadKey = ref(0);

onMounted(() => {
  fetchPolicy();
  fetchEmailStatus();
});

async function handleSavePolicy(allowance: number, warning: number) {
  await updatePolicy(allowance, warning);
}

async function handleSendTest(done: (result: { success: boolean; message: string }) => void) {
  done(await sendTestEmail());
}

function reloadAll() {
  fetchPolicy();
  fetchEmailStatus();
  reloadKey.value++;
}

function onChanged() {
  auditRef.value?.reload();
}
</script>

<template>
  <DashboardLayout :crumbs="['Sistem', 'Pengaturan']">
    <div class="mx-auto max-w-6xl space-y-5">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 class="text-2xl font-bold tracking-tight text-slate-900">Pengaturan Sistem</h1>
          <p class="mt-1 text-sm text-slate-500">
            Jatah free time, jam istirahat resmi, jadwal engine, dan email rekap.
          </p>
        </div>
        <Button variant="outline" size="sm" class="self-start sm:self-auto" :disabled="isLoading" @click="reloadAll">
          <RefreshCw class="h-4 w-4" :class="isLoading ? 'animate-spin' : ''" />
          Muat ulang
        </Button>
      </div>

      <DataSourceBanner :domains="['break-hours', 'engine-schedule', 'email-config', 'settings-audit']" />

      <div
          class="flex items-center justify-between gap-4 rounded-xl border border-slate-200 bg-white p-4"
        >
          <div>
            <h2 class="text-sm font-semibold text-slate-900">
              Status pengenalan pada video
            </h2>
            <p class="mt-1 text-xs text-slate-500">
              Tampilkan VERIFYING / IDENTIFYING pada bounding box.
              Proses AI dan timer tetap berjalan.
            </p>
          </div>

          <button
            type="button"
            role="switch"
            :aria-checked="showIdentityStatus"
            aria-label="Tampilkan status pengenalan pada video"
            class="shrink-0 rounded-lg border px-4 py-2 text-sm font-semibold transition-colors"
            :class="
              showIdentityStatus
                ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
                : 'border-slate-300 bg-slate-100 text-slate-500'
            "
            @click="toggleIdentityStatus"
          >
            {{ showIdentityStatus ? 'ON' : 'OFF' }}
          </button>
        </div>
      <Tabs v-model="tab" class="gap-4">
        <div class="-mx-1 overflow-x-auto px-1 pb-1">
          <TabsList class="w-max">
            <TabsTrigger value="allowance"><Clock />Jatah</TabsTrigger>
            <TabsTrigger value="break-hours"><CalendarClock />Jam istirahat</TabsTrigger>
            <TabsTrigger value="engine"><Cpu />Jadwal engine</TabsTrigger>
            <TabsTrigger value="email"><Mail />Email</TabsTrigger>
            <TabsTrigger value="history"><History />Riwayat</TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="allowance">
          <AllowanceTab
            :policy="policy"
            :is-saving="isSaving"
            :error="error"
            :success-message="successMessage"
            @save="handleSavePolicy"
          />
        </TabsContent>
        <TabsContent value="break-hours">
          <BreakHoursTab :key="`bh-${reloadKey}`" @changed="onChanged" />
        </TabsContent>
        <TabsContent value="engine">
          <EngineScheduleTab :key="`es-${reloadKey}`" @changed="onChanged" />
        </TabsContent>
        <TabsContent value="email">
          <EmailTab
            :key="`em-${reloadKey}`"
            :email-status="emailStatus"
            :is-sending-test-email="isSendingTestEmail"
            @send-test="handleSendTest"
            @changed="onChanged"
          />
        </TabsContent>
        <TabsContent value="history" :force-mount="true" class="data-[state=inactive]:hidden">
          <SettingsAuditLog ref="auditRef" :key="`au-${reloadKey}`" />
        </TabsContent>
      </Tabs>
    </div>
  </DashboardLayout>
</template>
