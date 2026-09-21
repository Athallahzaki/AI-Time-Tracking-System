import { ref, reactive } from 'vue';

export interface EnrolledPerson {
  person_id: string;
  enrollment_version: number;
  reference_count: number;
  enrolled_at?: string | null;
  last_seen_at?: string | null;
}

export interface EnrollmentSubmitResult {
  status: 'pending';
  request_id: string;
  person_id: string;
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      resolve(result.split(',')[1] || '');
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

const enrolledPersons = reactive<EnrolledPerson[]>([]);

export function useEnrollment() {
  const isLoadingList = ref(false);
  const listError = ref<string | null>(null);

  const isSubmitting = ref(false);
  const submitError = ref<string | null>(null);

  async function fetchEnrolledPersons() {
    isLoadingList.value = enrolledPersons.length === 0;
    try {
      const res = await fetch('/api/enrollments');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      if (json.status !== 'success' || !Array.isArray(json.enrollments)) {
        throw new Error('Bentuk respons /api/enrollments tidak dikenali');
      }
      enrolledPersons.splice(0, enrolledPersons.length, ...json.enrollments);
      listError.value = null;
    } catch (err: any) {
      listError.value =
        err?.message || 'Gagal memuat daftar karyawan terdaftar';
    } finally {
      isLoadingList.value = false;
    }
  }

  /**
   * Mengirim permintaan enrollment.
   *
   * PENTING: endpoint ini cuma mengembalikan {status: "pending", request_id,
   * person_id} — sekadar tanda terkirim, BUKAN hasil sebenarnya (diterima/
   * ditolak, alasan per gambar seperti too_small/blurry/duplicate_of, info
   * tabrakan dengan karyawan lain).
   *
   * Sesuai pola async ENGINE_PROTOCOL.md §3.5, hasil sebenarnya (enroll_result)
   * datang belakangan dari engine. Saya belum tahu jalurnya sampai ke
   * frontend — belum lihat services/enrollment_service.py atau bagian yang
   * menangani pesan masuk dari engine_client. Jangan anggap "pending" berarti
   * "berhasil".
   */
  async function submitEnrollment(
    personId: string,
    images: File[],
  ): Promise<EnrollmentSubmitResult> {
    isSubmitting.value = true;
    submitError.value = null;
    try {
      const encodedImages = await Promise.all(
        images.map(async (file, idx) => ({
          id: `img${idx + 1}`,
          jpeg_b64: await fileToBase64(file),
        })),
      );

      const res = await fetch('/api/enrollments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ person_id: personId, images: encodedImages }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body?.detail || `HTTP ${res.status}`);
      }

      return await res.json();
    } catch (err: any) {
      submitError.value =
        err?.message || 'Gagal mengirim permintaan enrollment';
      throw err;
    } finally {
      isSubmitting.value = false;
    }
  }

  return {
    enrolledPersons,
    isLoadingList,
    listError,
    fetchEnrolledPersons,
    isSubmitting,
    submitError,
    submitEnrollment,
  };
}
