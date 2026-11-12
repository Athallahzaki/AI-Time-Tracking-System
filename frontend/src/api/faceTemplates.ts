// Template wajah dari CCTV (docs/RENCANA-TEMPLATE-WAJAH.md). Backend hanya mendaftarkan
// rute ini bila FACE_TEMPLATES_ENABLED diisi; bila tidak, `request` melempar NotImplementedApiError.
import { request } from './http';

const DOMAIN = 'face-templates';

export type TemplateStatus =
  | 'pending' | 'queued' | 'review' | 'approved' | 'applied' | 'failed' | 'rejected' | 'discarded' | 'removed';

export interface FaceTemplateSettings {
  active: boolean;
  mode: 'otomatis' | 'persetujuan';
  apply_time: string;
  review_margin: number;
  duplicate_similarity: number;
  outlier_drop: number;
  max_per_person_per_day: number;
  max_per_person: number;
  max_age_days: number;
  pull_interval_seconds: number;
}

export interface FaceTemplateStatus {
  settings: FaceTemplateSettings;
  counts: Partial<Record<TemplateStatus, number>>;
  engine_connected: boolean;
  engine_supported: boolean | null;
  engine_reason: string | null;
  embedding_version: string | null;
  last_apply: Record<string, number> | null;
  last_error: string | null;
}

export interface FaceTemplateCandidate {
  id: number;
  candidate_id: string;
  person_id: string;
  camera_id: string;
  captured_at: string;
  track_uuid: string | null;
  embedding_version: string;
  anchor_similarity: number;
  margin: number;
  runner_up_id: string | null;
  runner_up_similarity: number | null;
  face_px: number;
  det_score: number;
  yaw: number | null;
  status: TemplateStatus;
  reason: string | null;
  reference_id: number | null;
  created_at: number;
  decided_by: string | null;
  decided_at: number | null;
  applied_at: number | null;
  has_image: boolean;
}

export function getTemplateStatus(): Promise<FaceTemplateStatus> {
  return request({ domain: DOMAIN, path: '/api/face-templates/status' });
}

export function saveTemplateSettings(values: Partial<FaceTemplateSettings>): Promise<FaceTemplateSettings> {
  return request({ domain: DOMAIN, method: 'PUT', path: '/api/face-templates/settings', body: values });
}

export function listTemplates(status: string, personId: string): Promise<FaceTemplateCandidate[]> {
  const query = new URLSearchParams({ limit: '120' });
  if (status) query.set('status', status);
  if (personId) query.set('person_id', personId);
  return request({ domain: DOMAIN, path: `/api/face-templates?${query}` });
}

/** Gambar crop wajah sebagai object URL; pemanggil wajib `URL.revokeObjectURL`. */
export async function templateImageUrl(id: number): Promise<string> {
  const res = await request<Response>({ domain: DOMAIN, path: `/api/face-templates/${id}/image`, raw: true });
  return URL.createObjectURL(await res.blob());
}

export function approveTemplate(id: number): Promise<FaceTemplateCandidate> {
  return request({ domain: DOMAIN, method: 'POST', path: `/api/face-templates/${id}/approve` });
}

export function discardTemplate(id: number): Promise<FaceTemplateCandidate> {
  return request({ domain: DOMAIN, method: 'POST', path: `/api/face-templates/${id}/discard` });
}

export function weighTemplates(): Promise<{ pulled: number | null; result: Record<string, number> }> {
  return request({ domain: DOMAIN, method: 'POST', path: '/api/face-templates/weigh' });
}

export function applyTemplatesNow(): Promise<Record<string, number>> {
  return request({ domain: DOMAIN, method: 'POST', path: '/api/face-templates/apply-now' });
}
