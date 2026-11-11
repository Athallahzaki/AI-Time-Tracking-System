<script setup>
import { computed, ref, watch } from 'vue';
import { AlertTriangle, X } from '@lucide/vue';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  createEmployee,
  createExemption,
  listCameraOptions,
  listExemptions,
  revokeExemption,
  updateEmployee,
} from '@/api/employees';
import { nativeSelectClass } from '@/components/common/nativeSelect';
import { isValidEmail } from '@/lib/format';

const props = defineProps({
  open: { type: Boolean, default: false },
  /** null = tambah baru; objek Employee = edit. */
  employee: { type: Object, default: null },
  divisions: { type: Array, default: () => [] },
});

const emit = defineEmits(['update:open', 'saved']);

const form = ref({ employee_id: '', name: '', division: '', email: '', allowance_minutes: '' });

// Pengecualian lokasi: hanya saat mengubah karyawan yang sudah ada.
const cameras = ref([]);
const exemptions = ref([]);
const exemptionForm = ref({ camera_id: '', reason: '' });
const exemptionError = ref('');
const exemptionBusy = ref(false);
const activeExemptions = computed(() => exemptions.value.filter((x) => x.revoked_at === null));
const cameraName = (id) => cameras.value.find((c) => c.id === id)?.name || id;
const errors = ref({});
const serverError = ref('');
const saving = ref(false);

const isEdit = computed(() => !!props.employee);
const idChanged = computed(
  () => isEdit.value && form.value.employee_id.trim() !== props.employee.employee_id,
);

watch(
  () => props.open,
  (isOpen) => {
    if (!isOpen) return;
    const e = props.employee;
    form.value = {
      employee_id: e?.employee_id ?? '',
      name: e?.name ?? '',
      division: e?.division ?? '',
      email: e?.email ?? '',
      allowance_minutes: e?.allowance_minutes ?? '',
    };
    errors.value = {};
    serverError.value = '';
    exemptions.value = [];
    exemptionForm.value = { camera_id: '', reason: '' };
    exemptionError.value = '';
    if (e) loadExemptions(e.uid);
  },
  { immediate: true },
);

async function loadExemptions(uid) {
  try {
    [cameras.value, exemptions.value] = await Promise.all([listCameraOptions(), listExemptions(uid)]);
  } catch (err) {
    exemptionError.value = err?.message || 'Gagal memuat pengecualian lokasi.';
  }
}

async function addExemption() {
  const { camera_id, reason } = exemptionForm.value;
  if (!camera_id || !reason.trim()) {
    exemptionError.value = 'Pilih lokasi dan isi alasannya.';
    return;
  }
  exemptionBusy.value = true;
  exemptionError.value = '';
  try {
    exemptions.value.push(await createExemption(props.employee.uid, camera_id, reason.trim()));
    exemptionForm.value = { camera_id: '', reason: '' };
  } catch (err) {
    exemptionError.value = err?.message || 'Gagal menambah pengecualian.';
  } finally {
    exemptionBusy.value = false;
  }
}

async function removeExemption(item) {
  exemptionBusy.value = true;
  exemptionError.value = '';
  try {
    await revokeExemption(props.employee.uid, item.id);
    item.revoked_at = Date.now() / 1000;
  } catch (err) {
    exemptionError.value = err?.message || 'Gagal mencabut pengecualian.';
  } finally {
    exemptionBusy.value = false;
  }
}

function validate() {
  const next = {};
  const f = form.value;
  if (!f.employee_id.trim()) next.employee_id = 'ID karyawan wajib diisi.';
  else if (!/^[A-Za-z0-9._-]{1,50}$/.test(f.employee_id.trim()))
    next.employee_id = 'Hanya huruf, angka, titik, garis bawah, atau strip (maks. 50).';
  if (!f.name.trim()) next.name = 'Nama wajib diisi.';
  if (f.email.trim() && !isValidEmail(f.email)) next.email = 'Format email tidak valid.';
  const allowance = String(f.allowance_minutes ?? '').trim();
  if (allowance && !(Number(allowance) > 0 && Number(allowance) <= 1440))
    next.allowance_minutes = 'Isi 1 sampai 1440 menit, atau kosongkan.';
  errors.value = next;
  return Object.keys(next).length === 0;
}

async function submit() {
  if (!validate()) return;
  saving.value = true;
  serverError.value = '';
  const payload = {
    employee_id: form.value.employee_id.trim(),
    name: form.value.name.trim(),
    division: form.value.division.trim() || null,
    email: form.value.email.trim() || null,
    // Kosong = null = kembali ke jatah global.
    allowance_minutes: String(form.value.allowance_minutes ?? '').trim()
      ? Number(form.value.allowance_minutes)
      : null,
  };
  try {
    const saved = isEdit.value
      ? await updateEmployee(props.employee.uid, payload)
      : await createEmployee(payload);
    emit('saved', saved);
    emit('update:open', false);
  } catch (err) {
    if (err?.status === 409) errors.value = { ...errors.value, employee_id: err.message };
    else serverError.value = err?.message || 'Gagal menyimpan data karyawan.';
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="(v) => emit('update:open', v)">
    <DialogContent class="sm:max-w-lg">
      <DialogHeader>
        <DialogTitle>{{ isEdit ? 'Ubah data karyawan' : 'Tambah karyawan' }}</DialogTitle>
        <DialogDescription>
          Data master dipakai untuk enrollment wajah, akun karyawan, dan tujuan email pelanggaran.
        </DialogDescription>
      </DialogHeader>

      <form id="employee-form" class="space-y-4" @submit.prevent="submit">
        <div class="grid gap-4 sm:grid-cols-2">
          <div class="space-y-1.5">
            <Label for="emp-id" class="text-xs font-semibold text-slate-700">
              ID karyawan <span class="text-red-500">*</span>
            </Label>
            <Input id="emp-id" v-model="form.employee_id" placeholder="mis. EMP011" :aria-invalid="!!errors.employee_id" />
            <p v-if="errors.employee_id" class="text-[11px] text-red-600">{{ errors.employee_id }}</p>
          </div>
          <div class="space-y-1.5">
            <Label for="emp-name" class="text-xs font-semibold text-slate-700">
              Nama <span class="text-red-500">*</span>
            </Label>
            <Input id="emp-name" v-model="form.name" placeholder="Nama lengkap" :aria-invalid="!!errors.name" />
            <p v-if="errors.name" class="text-[11px] text-red-600">{{ errors.name }}</p>
          </div>
          <div class="space-y-1.5">
            <Label for="emp-division" class="text-xs font-semibold text-slate-700">Divisi</Label>
            <Input id="emp-division" v-model="form.division" list="division-options" placeholder="mis. Produksi" />
            <datalist id="division-options">
              <option v-for="d in divisions" :key="d" :value="d" />
            </datalist>
          </div>
          <div class="space-y-1.5">
            <Label for="emp-email" class="text-xs font-semibold text-slate-700">Email</Label>
            <Input id="emp-email" v-model="form.email" type="email" placeholder="nama@perusahaan.com" :aria-invalid="!!errors.email" />
            <p v-if="errors.email" class="text-[11px] text-red-600">{{ errors.email }}</p>
            <p v-else-if="!form.email.trim()" class="text-[11px] text-amber-700">
              Tanpa email, peringatan pelanggaran hanya dikirim ke HR.
            </p>
          </div>
          <div class="space-y-1.5">
            <Label for="emp-allowance" class="text-xs font-semibold text-slate-700">
              Jatah free time harian (menit)
            </Label>
            <Input
              id="emp-allowance"
              v-model="form.allowance_minutes"
              type="number"
              min="1"
              max="1440"
              step="1"
              placeholder="Kosong = jatah global"
              :aria-invalid="!!errors.allowance_minutes"
            />
            <p v-if="errors.allowance_minutes" class="text-[11px] text-red-600">{{ errors.allowance_minutes }}</p>
          </div>
        </div>

        <fieldset v-if="isEdit" class="space-y-2 rounded-md border border-slate-200 px-3 py-3">
          <legend class="px-1 text-xs font-semibold text-slate-700">Pengecualian lokasi</legend>
          <p class="text-[11px] text-slate-500">
            Kunjungan karyawan ini di lokasi yang dikecualikan tetap tercatat, tetapi tidak memotong jatah.
            Berlaku sejak ditambahkan, tidak mundur.
          </p>
          <ul v-if="activeExemptions.length" class="space-y-1">
            <li
              v-for="item in activeExemptions"
              :key="item.id"
              class="flex items-center justify-between gap-2 rounded bg-slate-50 px-2 py-1.5 text-xs"
            >
              <span>
                <b>{{ cameraName(item.camera_id) }}</b>
                <span class="text-slate-500"> · {{ item.reason }} · oleh {{ item.created_by }}</span>
              </span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                :disabled="exemptionBusy"
                :aria-label="`Cabut pengecualian ${cameraName(item.camera_id)}`"
                @click="removeExemption(item)"
              >
                <X class="h-3.5 w-3.5" /> Cabut
              </Button>
            </li>
          </ul>
          <p v-else class="text-[11px] text-slate-500">Belum ada pengecualian aktif.</p>
          <div class="grid gap-2 sm:grid-cols-[1fr_1.4fr_auto]">
            <select v-model="exemptionForm.camera_id" :class="nativeSelectClass" aria-label="Lokasi yang dikecualikan">
              <option value="">Pilih lokasi…</option>
              <option
                v-for="c in cameras"
                :key="c.id"
                :value="c.id"
                :disabled="activeExemptions.some((x) => x.camera_id === c.id)"
              >
                {{ c.name }}{{ c.counts_free_time === false ? ' (tidak dihitung)' : '' }}
              </option>
            </select>
            <Input v-model="exemptionForm.reason" placeholder="Alasan (wajib)" aria-label="Alasan pengecualian" />
            <Button type="button" variant="outline" :disabled="exemptionBusy" @click="addExemption">Tambah</Button>
          </div>
          <p v-if="exemptionError" class="text-[11px] text-red-600">{{ exemptionError }}</p>
        </fieldset>

        <div
          v-if="idChanged"
          class="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900"
        >
          <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            ID karyawan diubah dari <b class="font-mono">{{ employee.employee_id }}</b>. Referensi wajah dan
            riwayat tetap tersambung karena sistem memakai kunci internal, tetapi username akun karyawan
            (bila ada) tidak ikut berubah.
          </p>
        </div>

        <p v-if="serverError" class="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">{{ serverError }}</p>
      </form>

      <DialogFooter>
        <Button variant="outline" :disabled="saving" @click="emit('update:open', false)">Batal</Button>
        <Button type="submit" form="employee-form" :disabled="saving">
          {{ saving ? 'Menyimpan…' : isEdit ? 'Simpan perubahan' : 'Tambah karyawan' }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
