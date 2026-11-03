<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { AlertCircle, CheckCircle2, Clock, MonitorPlay, RotateCcw, Save, SlidersHorizontal } from '@lucide/vue';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { getEngineTuning, saveDisplaySettings, saveEngineTuning } from '@/api/settings';
import { DEFAULT_DISPLAY_CONFIG, applyDisplayConfig, displayConfig, mergeDisplayConfig } from '@/config/display';

// Kalibrasi realtime (overhaul 3 Nov). Engine: override di atas config file-nya, dikirim
// sebagai set_tuning tanpa restart; daftar kunci datang dari engine sendiri (effective_tuning).
// Tampilan: disimpan di backend, berlaku di dashboard ini segera dan di browser lain saat refresh.
const emit = defineEmits(['changed']);

const SECTION_LABELS = {
  recognition: 'Identitas wajah',
  reid: 'ReID (tubuh, lintas kamera)',
  analysis_trigger: 'Pemicu analisis (perubahan kotak)',
  detector: 'Detektor',
  core: 'Kamera kosong (hemat GPU)',
  webrtc: 'WebRTC',
  hls: 'HLS',
  boxes: 'Kotak deteksi',
  interpolation: 'Interpolasi kotak',
};
const KEY_HINTS = {
  'recognition.match_threshold': 'Kemiripan wajah minimum. Kosong = default engine.',
  'recognition.match_margin': 'Selisih minimum dari kandidat kedua.',
  'recognition.cross_camera_claims': 'Satu nama tidak boleh di dua kamera sekaligus kecuali tumpang-tindih.',
  'recognition.overlapping_cameras': 'Pasangan camera_id yang bidang pandangnya tumpang-tindih, mis. [["cam01","cam02"]].',
  'reid.match_threshold': 'Kemiripan tubuh minimum. Kalibrasi dulu dengan eval_reid.py.',
  'reid.travel_time_seconds': 'Waktu tempuh minimum antar lokasi (detik), mis. {"lobby":{"biliar":20}}.',
  'reid.reevaluate': 'Nilai ulang kelompok ANON di setiap embedding baru. Nyalakan setelah kalibrasi.',
  'analysis_trigger.enabled': 'Analisis saat kotak berubah, bukan interval tetap.',
  'detector.nms_iou_threshold': 'Kosong = NMS mati. Usulan 0,7.',
  'core.idle_fps': 'fps detector saat kamera kosong. Kosong = mati.',
};
const RESTART_NOTE = 'Butuh restart engine: semua pengaturan tracker (mis. track_threshold), model, ukuran input.';

// ---------------- engine ----------------
const tuning = ref(null);
const draft = ref({});
const loading = ref(false);
const saving = ref(false);
const error = ref('');
const message = ref('');
let poll = null;

const effective = computed(() => tuning.value?.status?.effective || null);
const status = computed(() => tuning.value?.status || {});
const dirty = computed(() => JSON.stringify(draft.value) !== JSON.stringify(tuning.value?.overrides || {}));

function clone(value) {
  return JSON.parse(JSON.stringify(value ?? {}));
}
function isOverridden(section, key) {
  return draft.value[section] && Object.prototype.hasOwnProperty.call(draft.value[section], key);
}
function valueOf(section, key) {
  return isOverridden(section, key) ? draft.value[section][key] : effective.value?.[section]?.[key];
}
function kindOf(section, key) {
  const value = effective.value?.[section]?.[key];
  if (typeof value === 'boolean') return 'bool';
  if (value !== null && typeof value === 'object') return 'json';
  return 'number';
}
function textOf(section, key) {
  const value = valueOf(section, key);
  if (value === null || value === undefined) return '';
  return kindOf(section, key) === 'json' ? JSON.stringify(value) : String(value);
}
const fieldErrors = ref({});
function setOverride(section, key, value) {
  draft.value = { ...draft.value, [section]: { ...(draft.value[section] || {}), [key]: value } };
}
function onBool(section, key, value) {
  setOverride(section, key, value);
}
function onText(section, key, raw) {
  const id = `${section}.${key}`;
  const text = raw.trim();
  const errors = { ...fieldErrors.value };
  delete errors[id];
  let value;
  if (kindOf(section, key) === 'json') {
    try {
      value = JSON.parse(text || 'null');
    } catch {
      errors[id] = 'JSON tidak valid';
    }
  } else if (text === '') {
    value = null;
  } else if (Number.isFinite(Number(text.replace(',', '.')))) {
    value = Number(text.replace(',', '.'));
  } else {
    errors[id] = 'Harus angka (atau kosong)';
  }
  fieldErrors.value = errors;
  if (!errors[id]) setOverride(section, key, value);
}
function resetKey(section, key) {
  const next = clone(draft.value);
  delete next[section][key];
  if (!Object.keys(next[section]).length) delete next[section];
  draft.value = next;
  const errors = { ...fieldErrors.value };
  delete errors[`${section}.${key}`];
  fieldErrors.value = errors;
}

async function load() {
  loading.value = true;
  error.value = '';
  try {
    tuning.value = await getEngineTuning();
    draft.value = clone(tuning.value.overrides);
  } catch (err) {
    error.value = err?.message || 'Gagal memuat kalibrasi engine.';
  } finally {
    loading.value = false;
  }
}

function watchStatus() {
  clearInterval(poll);
  let tries = 0;
  poll = setInterval(async () => {
    tries += 1;
    try {
      const fresh = await getEngineTuning();
      tuning.value = fresh;
      if (fresh.status?.state !== 'pending' || tries >= 15) {
        clearInterval(poll);
        draft.value = clone(fresh.overrides);
        if (fresh.status?.state === 'accepted') message.value = 'Diterapkan engine tanpa restart.';
        else if (fresh.status?.state === 'rejected') error.value = `Ditolak engine: ${fresh.status.reason}`;
        else if (fresh.status?.state === 'pending') error.value = 'Engine belum membalas; cek koneksi engine.';
      }
    } catch {
      /* coba lagi di detak berikutnya */
    }
  }, 1000);
}

async function saveEngine() {
  if (Object.keys(fieldErrors.value).length) return;
  saving.value = true;
  error.value = '';
  message.value = '';
  try {
    tuning.value = await saveEngineTuning(clone(draft.value));
    emit('changed');
    if (tuning.value.status?.state === 'offline') {
      message.value = 'Disimpan. Engine tidak tersambung; diterapkan saat tersambung.';
    } else {
      message.value = 'Dikirim ke engine, menunggu balasan...';
      watchStatus();
    }
  } catch (err) {
    error.value = err?.message || 'Gagal menyimpan kalibrasi.';
  } finally {
    saving.value = false;
  }
}

// ---------------- tampilan ----------------
const displayDraft = ref(clone(displayConfig));
const displayMessage = ref('');
const displayError = ref('');
const displayWarnings = computed(() => mergeDisplayConfig(displayDraft.value).warnings);
function displayKind(section, key) {
  const value = DEFAULT_DISPLAY_CONFIG[section][key];
  return typeof value === 'boolean' ? 'bool' : 'number';
}
function onDisplay(section, key, raw) {
  let value = raw;
  if (displayKind(section, key) === 'number') {
    const text = String(raw).trim().replace(',', '.');
    value = text === '' ? null : Number(text);
  }
  displayDraft.value = { ...displayDraft.value, [section]: { ...displayDraft.value[section], [key]: value } };
}
async function saveDisplay() {
  displayError.value = '';
  displayMessage.value = '';
  if (displayWarnings.value.length) {
    displayError.value = displayWarnings.value.join('; ');
    return;
  }
  try {
    await saveDisplaySettings(clone(displayDraft.value));
    applyDisplayConfig(displayDraft.value);
    displayMessage.value = 'Disimpan. Berlaku di sini sekarang; browser lain saat di-refresh.';
    emit('changed');
  } catch (err) {
    displayError.value = err?.message || 'Gagal menyimpan tampilan.';
  }
}

onMounted(load);
onBeforeUnmount(() => clearInterval(poll));
</script>

<template>
  <div class="grid gap-4">
    <Card>
      <CardHeader>
        <CardTitle class="flex items-center gap-2"><SlidersHorizontal class="size-4" />Kalibrasi engine (realtime)</CardTitle>
        <CardDescription>
          Nilai di atas config file engine, berlaku tanpa restart. Kosongkan override (tombol reset) untuk kembali ke file.
          {{ RESTART_NOTE }}
        </CardDescription>
      </CardHeader>
      <CardContent class="grid gap-5">
        <p v-if="loading" class="text-muted-foreground text-sm">Memuat...</p>
        <p v-else-if="!effective" class="text-muted-foreground text-sm">
          Nilai yang berlaku tampil setelah engine membalas.
          {{ tuning?.engine_connected ? 'Simpan sekali untuk memintanya.' : 'Engine tidak tersambung.' }}
        </p>
        <template v-else>
          <section v-for="(keys, section) in effective" :key="section" class="grid gap-2">
            <h3 class="text-sm font-medium">{{ SECTION_LABELS[section] || section }}</h3>
            <div v-for="(_, key) in keys" :key="key"
                 class="grid items-start gap-2 sm:grid-cols-[14rem_1fr_auto]">
              <label :for="`t-${section}-${key}`" class="pt-1.5 text-sm">
                <code class="text-xs">{{ key }}</code>
                <span v-if="isOverridden(section, key)" class="text-primary ml-1 text-xs">(diubah)</span>
              </label>
              <div class="grid gap-1">
                <Switch v-if="kindOf(section, key) === 'bool'" :id="`t-${section}-${key}`"
                        :model-value="!!valueOf(section, key)"
                        @update:model-value="(v) => onBool(section, key, v)" />
                <input v-else :id="`t-${section}-${key}`" :value="textOf(section, key)"
                       :placeholder="kindOf(section, key) === 'json' ? 'JSON' : 'kosong = default'"
                       class="border-input h-8 rounded-md border bg-transparent px-2 text-sm shadow-xs outline-none focus-visible:border-ring"
                       @change="(e) => onText(section, key, e.target.value)" />
                <p v-if="fieldErrors[`${section}.${key}`]" class="text-destructive text-xs">
                  {{ fieldErrors[`${section}.${key}`] }}
                </p>
                <p v-else-if="KEY_HINTS[`${section}.${key}`]" class="text-muted-foreground text-xs">
                  {{ KEY_HINTS[`${section}.${key}`] }}
                </p>
              </div>
              <Button v-if="isOverridden(section, key)" variant="ghost" size="sm"
                      :aria-label="`Kembalikan ${key} ke config file`" @click="resetKey(section, key)">
                <RotateCcw />
              </Button>
            </div>
          </section>
        </template>
        <p class="text-muted-foreground flex items-center gap-1 text-xs">
          <Clock class="size-3" />Status: {{ status.state || '-' }}<span v-if="status.at">, {{ status.at }}</span>
        </p>
      </CardContent>
      <CardFooter class="flex flex-wrap items-center gap-3">
        <Button :disabled="saving || !dirty || Object.keys(fieldErrors).length > 0" @click="saveEngine">
          <Save />Simpan & terapkan
        </Button>
        <span v-if="message" class="flex items-center gap-1 text-sm text-emerald-600" role="status">
          <CheckCircle2 class="size-4" />{{ message }}
        </span>
        <span v-if="error" class="text-destructive flex items-center gap-1 text-sm" role="alert">
          <AlertCircle class="size-4" />{{ error }}
        </span>
      </CardFooter>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle class="flex items-center gap-2"><MonitorPlay class="size-4" />Tampilan dashboard</CardTitle>
        <CardDescription>
          Delay video dan perilaku kotak. Ditumpuk di atas display-config.json server. Kosong = tanpa batas / default hls.js.
        </CardDescription>
      </CardHeader>
      <CardContent class="grid gap-5">
        <section v-for="(keys, section) in DEFAULT_DISPLAY_CONFIG" :key="section" class="grid gap-2">
          <h3 class="text-sm font-medium">{{ SECTION_LABELS[section] || section }}</h3>
          <div v-for="(_, key) in keys" :key="key" class="grid items-center gap-2 sm:grid-cols-[14rem_1fr]">
            <label :for="`d-${section}-${key}`" class="text-sm"><code class="text-xs">{{ key }}</code></label>
            <Switch v-if="displayKind(section, key) === 'bool'" :id="`d-${section}-${key}`"
                    :model-value="!!displayDraft[section][key]"
                    @update:model-value="(v) => onDisplay(section, key, v)" />
            <input v-else :id="`d-${section}-${key}`"
                   :value="displayDraft[section][key] ?? ''"
                   class="border-input h-8 rounded-md border bg-transparent px-2 text-sm shadow-xs outline-none focus-visible:border-ring"
                   @change="(e) => onDisplay(section, key, e.target.value)" />
          </div>
        </section>
      </CardContent>
      <CardFooter class="flex flex-wrap items-center gap-3">
        <Button @click="saveDisplay"><Save />Simpan tampilan</Button>
        <span v-if="displayMessage" class="flex items-center gap-1 text-sm text-emerald-600" role="status">
          <CheckCircle2 class="size-4" />{{ displayMessage }}
        </span>
        <span v-if="displayError" class="text-destructive flex items-center gap-1 text-sm" role="alert">
          <AlertCircle class="size-4" />{{ displayError }}
        </span>
      </CardFooter>
    </Card>
  </div>
</template>
