<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { Check, ChevronsUpDown, Search, UserRound } from '@lucide/vue';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { listEmployees } from '@/api/employees';
import { cn } from '@/lib/utils';

// Combobox karyawan dengan pencarian ID / nama (dok. 12 §3.1). Nilai = uid
// karyawan (kunci internal), bukan teks ketikan.
const props = defineProps({
  modelValue: { type: String, default: '' },
  /** Bila diisi, daftar ini yang dipakai (tidak mengambil sendiri). */
  employees: { type: Array, default: null },
  activeOnly: { type: Boolean, default: true },
  placeholder: { type: String, default: 'Pilih karyawan…' },
  allowClear: { type: Boolean, default: false },
  clearLabel: { type: String, default: 'Semua karyawan' },
  id: { type: String, default: undefined },
  disabled: { type: Boolean, default: false },
});

const emit = defineEmits(['update:modelValue', 'select']);

const open = ref(false);
const query = ref('');
const loaded = ref([]);
const loading = ref(false);
const loadError = ref('');
const highlighted = ref(0);
const inputRef = ref(null);

const source = computed(() => {
  const list = props.employees ?? loaded.value;
  return props.activeOnly ? list.filter((e) => e.active) : list;
});

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase();
  const list = !q
    ? source.value
    : source.value.filter((e) =>
        `${e.employee_id} ${e.name} ${e.division || ''}`.toLowerCase().includes(q),
      );
  return list.slice(0, 100);
});

const selected = computed(() =>
  (props.employees ?? loaded.value).find((e) => e.uid === props.modelValue) || null,
);

async function load() {
  if (props.employees) return;
  loading.value = true;
  loadError.value = '';
  try {
    loaded.value = await listEmployees({ status: 'all' });
  } catch (err) {
    loadError.value = err?.message || 'Gagal memuat karyawan';
  } finally {
    loading.value = false;
  }
}

onMounted(load);
defineExpose({ reload: load });

watch(open, async (isOpen) => {
  if (isOpen) {
    query.value = '';
    highlighted.value = 0;
    await nextTick();
    inputRef.value?.focus();
  }
});
watch(query, () => {
  highlighted.value = 0;
});

function choose(employee) {
  emit('update:modelValue', employee ? employee.uid : '');
  emit('select', employee);
  open.value = false;
}

function onKeydown(event) {
  if (event.key === 'ArrowDown') {
    event.preventDefault();
    highlighted.value = Math.min(highlighted.value + 1, filtered.value.length - 1);
  } else if (event.key === 'ArrowUp') {
    event.preventDefault();
    highlighted.value = Math.max(highlighted.value - 1, 0);
  } else if (event.key === 'Enter') {
    event.preventDefault();
    const item = filtered.value[highlighted.value];
    if (item) choose(item);
  }
}
</script>

<template>
  <Popover v-model:open="open">
    <PopoverTrigger as-child>
      <button
        :id="id"
        type="button"
        role="combobox"
        :aria-expanded="open"
        :disabled="disabled"
        :class="
          cn(
            'border-input flex h-9 w-full items-center justify-between gap-2 rounded-md border bg-transparent px-3 text-left text-sm shadow-xs outline-none',
            'focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-3 disabled:cursor-not-allowed disabled:opacity-50',
          )
        "
      >
        <span v-if="selected" class="flex min-w-0 items-center gap-2">
          <span class="font-mono text-xs font-semibold text-slate-700">{{ selected.employee_id }}</span>
          <span class="truncate text-slate-800">{{ selected.name }}</span>
        </span>
        <span v-else class="truncate text-slate-400">{{ allowClear && !modelValue ? clearLabel : placeholder }}</span>
        <ChevronsUpDown class="h-4 w-4 shrink-0 text-slate-400" />
      </button>
    </PopoverTrigger>
    <PopoverContent align="start" class="w-(--reka-popover-trigger-width) min-w-72 p-0">
      <div class="flex items-center gap-2 border-b px-3">
        <Search class="h-4 w-4 shrink-0 text-slate-400" />
        <input
          ref="inputRef"
          v-model="query"
          class="h-10 w-full bg-transparent text-sm outline-none placeholder:text-slate-400"
          placeholder="Cari ID atau nama…"
          @keydown="onKeydown"
        />
      </div>
      <div class="max-h-64 overflow-y-auto p-1">
        <button
          v-if="allowClear"
          type="button"
          class="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm text-slate-600 hover:bg-slate-100"
          @click="choose(null)"
        >
          <UserRound class="h-4 w-4 text-slate-400" />
          {{ clearLabel }}
        </button>
        <p v-if="loading" class="px-2 py-3 text-center text-xs text-slate-400">Memuat…</p>
        <p v-else-if="loadError" class="px-2 py-3 text-center text-xs text-red-600">{{ loadError }}</p>
        <template v-else>
          <button
            v-for="(e, i) in filtered"
            :key="e.uid"
            type="button"
            class="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm"
            :class="i === highlighted ? 'bg-indigo-50 text-indigo-900' : 'hover:bg-slate-100'"
            @mouseenter="highlighted = i"
            @click="choose(e)"
          >
            <Check
              class="h-4 w-4 shrink-0"
              :class="e.uid === modelValue ? 'text-indigo-600' : 'text-transparent'"
            />
            <span class="font-mono text-xs font-semibold text-slate-700">{{ e.employee_id }}</span>
            <span class="min-w-0 flex-1 truncate">{{ e.name }}</span>
            <span v-if="e.division" class="shrink-0 text-[11px] text-slate-400">{{ e.division }}</span>
            <span
              v-if="e.enrolled_refs > 0"
              class="shrink-0 rounded bg-emerald-50 px-1.5 text-[10px] font-medium text-emerald-700"
              title="Sudah punya referensi wajah"
            >{{ e.enrolled_refs }} foto</span>
          </button>
          <p v-if="!filtered.length" class="px-2 py-3 text-center text-xs text-slate-400">
            Tidak ada karyawan cocok.
          </p>
        </template>
      </div>
    </PopoverContent>
  </Popover>
</template>
