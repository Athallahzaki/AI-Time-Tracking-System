// Tabel memakai elemen HTML biasa + kelas utilitas di bawah, supaya tidak
// menambah lapisan komponen. Pakai: <table :class="tableClass.table"> dst.
export const tableClass = {
  wrapper: "relative w-full overflow-x-auto",
  table: "w-full caption-bottom text-sm",
  thead: "[&_tr]:border-b bg-slate-50/70",
  th: "h-9 px-3 text-left align-middle text-xs font-semibold whitespace-nowrap text-slate-500",
  tbody: "[&_tr:last-child]:border-0",
  tr: "border-b transition-colors hover:bg-slate-50/60",
  td: "px-3 py-2.5 align-middle",
} as const
