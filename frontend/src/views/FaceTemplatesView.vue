<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { Check, RefreshCw, ScanFace, Scale, Trash2, Upload } from '@lucide/vue';
import DashboardLayout from '@/layouts/DashboardLayout.vue';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { nativeSelectClass } from '@/components/common/nativeSelect';
import { NotImplementedApiError } from '@/api/http';
import {
  applyTemplatesNow,
  approveTemplate,
  discardTemplate,
  getTemplateStatus,
  listTemplates,
  saveTemplateSettings,
  templateImageUrl,
  weighTemplates,
} from '@/api/faceTemplates';
import { formatDateTime } from '@/lib/format';

// Template wajah dari CCTV (docs/RENCANA-TEMPLATE-WAJAH.md). Gambar adalah crop wajah
// karyawan: hanya dimuat sebagai object URL di memori halaman ini, dibuang saat keluar.
const STATUS_LABEL = {
  pending: 'Belum ditimbang',
  queued: 'Siap diterapkan',
  review: 'Perlu dilihat',
  approved: 'Disetujui',
  applied: 'Terpasang',
  failed: 'Ditolak engine',
  rejected: 'Ditolak sistem',
  discarded: 'Dibuang admin',
  removed: 'Dicabut',
};
const STATUS_CLASS = {
  pending: 'bg-slate-100 text-slate-700',
  queued: 'bg-sky-100 text-sky-800',
  review: 'bg-amber-100 text-amber-800',
  approved: 'bg-emerald-100 text-emerald-800',
  applied: 'bg-emerald-600 text-white',
  failed: 'bg-red-100 text-red-700',
  rejected: 'bg-red-100 text-red-700',
  discarded: 'bg-slate-200 text-slate-600',
  removed: 'bg-slate-200 text-slate-600',
};
const REASON_LABEL = {
  margin_tipis: 'mirip orang lain (margin tipis)',
  duplikat: 'terlalu mirip template yang sudah ada',
  pencilan: 'tidak sejalan dengan kandidat lain orang ini',
  batas_harian: 'batas harian per orang tercapai',
  versi_berbeda: 'versi model berbeda',
  dibuang_admin: 'dibuang admin',
  kedaluwarsa: 'kedaluwarsa',
  melebihi_batas: 'melebihi batas per orang',
  jangkar_rendah: 'tidak cocok dengan foto enrollment',
  tanpa_jangkar: 'karyawan belum punya enrollment',
};

const status = ref(null);
const form = ref(null);
const items = ref([]);
const images = ref({});
const statusFilter = ref('review');
const personFilter = ref('');
const disabled = ref(false);
const error = ref('');
const notice = ref('');
const busy = ref(false);

const counts = computed(() => status.value?.counts || {});
const engineNote = computed(() => {
  const s = status.value;
  if (!s) return '';
  if (!s.engine_connected) return 'Engine terputus';
  if (s.engine_supported === false) return `Engine tidak melayani template: ${s.engine_reason}`;
  if (s.engine_supported === null) return 'Belum ada jawaban dari engine';
  return `Engine siap · model ${s.embedding_version || '?'}`;
});

function reasonText(reason) {
  return reason ? REASON_LABEL[reason] || reason : '';
}

function fmt(value, digits = 2) {
  return typeof value === 'number' ? value.toFixed(digits) : '–';
}

async function run(action, message) {
  busy.value = true;
  error.value = '';
  notice.value = '';
  try {
    const result = await action();
    if (message) notice.value = message(result);
    await refresh();
  } catch (err) {
    error.value = err?.message || String(err);
  } finally {
    busy.value = false;
  }
}

function releaseImages() {
  Object.values(images.value).forEach((url) => URL.revokeObjectURL(url));
  images.value = {};
}

async function refresh() {
  try {
    status.value = await getTemplateStatus();
    if (!form.value) form.value = { ...status.value.settings };
    items.value = await listTemplates(statusFilter.value, personFilter.value.trim());
    disabled.value = false;
  } catch (err) {
    if (err instanceof NotImplementedApiError) disabled.value = true;
    else error.value = err?.message || String(err);
    return;
  }
  const keep = new Set(items.value.filter((item) => item.has_image).map((item) => item.id));
  for (const [id, url] of Object.entries(images.value)) {
    if (!keep.has(Number(id))) {
      URL.revokeObjectURL(url);
      delete images.value[id];
    }
  }
  for (const id of keep) {
    if (!images.value[id]) {
      templateImageUrl(id)
        .then((url) => (images.value = { ...images.value, [id]: url }))
        .catch(() => {});
    }
  }
}

function saveSettings() {
  run(async () => {
    form.value = { ...(await saveTemplateSettings(form.value)) };
  }, () => 'Pengaturan disimpan.');
}

const weigh = () =>
  run(weighTemplates, (r) => `Ditarik ${r.pulled ?? 0} kandidat; ditimbang: ${JSON.stringify(r.result)}`);
const applyNow = () =>
  run(applyTemplatesNow, (r) => `Terpasang ${r.applied}, ditolak engine ${r.failed}, dicabut ${r.removed}.`);
const approve = (item) => run(() => approveTemplate(item.id));
function discard(item) {
  const what = item.status === 'applied' ? 'Cabut template ini dari engine' : 'Buang kandidat ini';
  if (window.confirm(`${what}? Gambarnya dihapus dan tidak bisa dikembalikan.`)) {
    run(() => discardTemplate(item.id));
  }
}

watch(statusFilter, refresh);
onMounted(refresh);
onBeforeUnmount(releaseImages);
</script>

<template>
  <DashboardLayout :crumbs="['Sistem', 'Template Wajah']">
    <div class="mx-auto max-w-6xl space-y-5">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 class="flex items-center gap-2 text-2xl font-bold tracking-tight text-slate-900">
            <ScanFace class="h-6 w-6 text-sky-600" /> Template Wajah
          </h1>
          <p class="text-sm text-slate-500">
            Wajah dari kamera untuk karyawan yang sudah dikenali, supaya pengenalan di lokasi lebih kuat.
            Foto enrollment tidak pernah diubah.
          </p>
        </div>
        <Button variant="outline" :disabled="busy" @click="refresh">
          <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': busy }" /> Muat ulang
        </Button>
      </div>

      <Card v-if="disabled" class="p-5 text-sm text-slate-600">
        Fitur template wajah mati. Isi <code>FACE_TEMPLATES_ENABLED=1</code> di lingkungan backend dan
        <code>face_templates.enabled: true</code> di config engine, lalu restart keduanya.
      </Card>
      <p v-if="error" role="alert" class="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{{ error }}</p>
      <p v-if="notice" class="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{{ notice }}</p>

      <template v-if="status && form && !disabled">
        <Card class="space-y-4 p-5 text-sm">
          <div class="flex flex-wrap items-center gap-2">
            <Badge :class="status.engine_supported ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'">
              {{ engineNote }}
            </Badge>
            <Badge v-for="(label, key) in STATUS_LABEL" v-show="counts[key]" :key="key" :class="STATUS_CLASS[key]">
              {{ label }}: {{ counts[key] }}
            </Badge>
            <span v-if="status.last_error" class="text-red-700">Galat terakhir: {{ status.last_error }}</span>
          </div>

          <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label class="flex items-center gap-2">
              <input v-model="form.active" type="checkbox" class="h-4 w-4" />
              <span>Aktif (tarik dari engine &amp; terapkan terjadwal)</span>
            </label>
            <label class="space-y-1">
              <span class="text-slate-600">Mode</span>
              <select v-model="form.mode" :class="nativeSelectClass">
                <option value="otomatis">Otomatis: lolos penimbang diterapkan kecuali dibuang</option>
                <option value="persetujuan">Persetujuan: hanya yang disetujui admin</option>
              </select>
            </label>
            <label class="space-y-1">
              <span class="text-slate-600">Jam penerapan harian</span>
              <Input v-model="form.apply_time" type="time" />
            </label>
            <label class="space-y-1">
              <span class="text-slate-600">Margin minimum tanpa tinjau</span>
              <Input v-model.number="form.review_margin" type="number" step="0.01" min="0" max="1" />
            </label>
            <label class="space-y-1">
              <span class="text-slate-600">Ambang duplikat</span>
              <Input v-model.number="form.duplicate_similarity" type="number" step="0.01" min="0.5" max="1" />
            </label>
            <label class="space-y-1">
              <span class="text-slate-600">Toleransi pencilan</span>
              <Input v-model.number="form.outlier_drop" type="number" step="0.01" min="0" max="1" />
            </label>
            <label class="space-y-1">
              <span class="text-slate-600">Maks. baru per orang per hari</span>
              <Input v-model.number="form.max_per_person_per_day" type="number" min="1" max="50" />
            </label>
            <label class="space-y-1">
              <span class="text-slate-600">Maks. terpasang per orang · umur (hari)</span>
              <div class="flex gap-2">
                <Input v-model.number="form.max_per_person" type="number" min="1" max="200" />
                <Input v-model.number="form.max_age_days" type="number" min="1" max="365" />
              </div>
            </label>
          </div>
          <p class="text-xs text-slate-500">
            Angka penimbang belum dikalibrasi. Kandidat yang mirip orang lain tidak pernah diterapkan tanpa
            persetujuan. Penerapan terakhir:
            {{ status.last_apply ? formatDateTime(status.last_apply.at) : 'belum pernah' }}.
          </p>
          <div class="flex flex-wrap gap-2">
            <Button :disabled="busy" @click="saveSettings">Simpan pengaturan</Button>
            <Button variant="outline" :disabled="busy" @click="weigh"><Scale class="h-4 w-4" /> Timbang sekarang</Button>
            <Button variant="outline" :disabled="busy" @click="applyNow"><Upload class="h-4 w-4" /> Terapkan sekarang</Button>
          </div>
        </Card>

        <div class="flex flex-wrap items-end gap-3">
          <label class="space-y-1 text-sm">
            <span class="text-slate-600">Status</span>
            <select v-model="statusFilter" :class="nativeSelectClass" class="w-56">
              <option value="">Semua</option>
              <option v-for="(label, key) in STATUS_LABEL" :key="key" :value="key">{{ label }}</option>
            </select>
          </label>
          <label class="space-y-1 text-sm">
            <span class="text-slate-600">ID karyawan</span>
            <Input v-model="personFilter" class="w-48" placeholder="semua" @keyup.enter="refresh" />
          </label>
        </div>

        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Card v-for="item in items" :key="item.id" class="flex gap-3 p-3 text-xs">
            <div class="flex h-28 w-28 shrink-0 items-center justify-center overflow-hidden rounded bg-slate-100">
              <img v-if="images[item.id]" :src="images[item.id]" :alt="`Wajah ${item.person_id}`" class="h-full w-full object-contain" />
              <span v-else class="px-2 text-center text-slate-400">{{ item.has_image ? 'memuat…' : 'gambar dihapus' }}</span>
            </div>
            <div class="min-w-0 flex-1 space-y-1">
              <div class="flex items-center gap-2">
                <b class="truncate text-sm text-slate-900">{{ item.person_id }}</b>
                <Badge :class="STATUS_CLASS[item.status]">{{ STATUS_LABEL[item.status] }}</Badge>
              </div>
              <div class="text-slate-600">{{ item.camera_id }} · {{ formatDateTime(Date.parse(item.captured_at) / 1000) }}</div>
              <div>Ke enrollment <b>{{ fmt(item.anchor_similarity) }}</b> · margin <b :class="item.margin < 0.15 ? 'text-amber-700' : ''">{{ fmt(item.margin) }}</b></div>
              <div v-if="item.runner_up_id" class="text-slate-600">Terdekat lain: {{ item.runner_up_id }} ({{ fmt(item.runner_up_similarity) }})</div>
              <div class="text-slate-600">Wajah {{ Math.round(item.face_px) }} px · skor {{ fmt(item.det_score) }} · sudut {{ fmt(item.yaw) }}</div>
              <div v-if="item.reason" class="text-amber-800">{{ reasonText(item.reason) }}</div>
              <div v-if="item.decided_by" class="text-slate-500">oleh {{ item.decided_by }}</div>
              <div class="flex gap-2 pt-1">
                <Button v-if="['pending', 'queued', 'review'].includes(item.status)" size="sm" variant="outline" :disabled="busy" @click="approve(item)">
                  <Check class="h-3.5 w-3.5" /> Setujui
                </Button>
                <Button v-if="!['rejected', 'discarded', 'removed', 'failed'].includes(item.status)" size="sm" variant="outline" :disabled="busy" @click="discard(item)">
                  <Trash2 class="h-3.5 w-3.5" /> {{ item.status === 'applied' ? 'Cabut' : 'Buang' }}
                </Button>
              </div>
            </div>
          </Card>
          <p v-if="!items.length" class="text-sm text-slate-500">Tidak ada kandidat dengan filter ini.</p>
        </div>
      </template>
    </div>
  </DashboardLayout>
</template>
