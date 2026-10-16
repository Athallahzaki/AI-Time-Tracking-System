<script setup>
import { computed, ref, watch } from 'vue';
import { AlertTriangle } from '@lucide/vue';
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
import { createEmployee, updateEmployee } from '@/api/employees';
import { isValidEmail } from '@/lib/format';

const props = defineProps({
  open: { type: Boolean, default: false },
  /** null = tambah baru; objek Employee = edit. */
  employee: { type: Object, default: null },
  divisions: { type: Array, default: () => [] },
});

const emit = defineEmits(['update:open', 'saved']);

const form = ref({ employee_id: '', name: '', division: '', email: '' });
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
    };
    errors.value = {};
    serverError.value = '';
  },
  { immediate: true },
);

function validate() {
  const next = {};
  const f = form.value;
  if (!f.employee_id.trim()) next.employee_id = 'ID karyawan wajib diisi.';
  else if (!/^[A-Za-z0-9._-]{1,50}$/.test(f.employee_id.trim()))
    next.employee_id = 'Hanya huruf, angka, titik, garis bawah, atau strip (maks. 50).';
  if (!f.name.trim()) next.name = 'Nama wajib diisi.';
  if (f.email.trim() && !isValidEmail(f.email)) next.email = 'Format email tidak valid.';
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
        </div>

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
