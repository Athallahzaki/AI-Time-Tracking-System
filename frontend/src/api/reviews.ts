import { currentUsername } from '@/composables/useAuth';
import { ApiError, qs, request } from './http';
import { listEmployees } from './employees';
import { db, localDateString, save } from './mock/db';
import { datesBetween, reportRowFor, usageFor } from './mock/usage';
import type { ReviewDetail, ReviewItem, ReviewStatus } from './types';

/**
 * Antrean tinjauan HR (dok. 12 §3.6 butir 6): pelanggaran yang sebagian besar
 * menitnya bersumber ReID ditandai "perlu dicek HR".
 */
const DOMAIN = 'reviews';

export interface ReviewQuery {
  status?: ReviewStatus | 'all';
  from?: string;
  to?: string;
}

function defaultRange(): { from: string; to: string } {
  const to = new Date();
  const from = new Date();
  from.setDate(from.getDate() - 13);
  return { from: localDateString(from), to: localDateString(to) };
}

async function mockItems(query: ReviewQuery): Promise<ReviewItem[]> {
  const range = { ...defaultRange(), ...(query.from ? { from: query.from } : {}), ...(query.to ? { to: query.to } : {}) };
  const employees = await listEmployees({ status: 'all' });
  const decisions = db().reviewDecisions;
  const items: ReviewItem[] = [];
  for (const date of datesBetween(range.from, range.to).reverse()) {
    for (const e of employees) {
      const row = reportRowFor(e, date);
      if (!row.needs_review) continue;
      const id = `${e.uid}:${date}`;
      const decision = decisions[id];
      items.push({
        id,
        date,
        employee_uid: e.uid,
        employee_id: e.employee_id,
        name: e.name,
        used_seconds: row.used_seconds,
        allowance_seconds: row.allowance_seconds,
        reid_seconds: row.reid_seconds,
        visits: row.visits,
        status: decision?.status ?? 'pending',
        decided_by: decision?.by ?? null,
        decided_at: decision?.at ?? null,
        note: decision?.note ?? null,
      });
    }
  }
  const status = query.status || 'pending';
  return status === 'all' ? items : items.filter((i) => i.status === status);
}

export async function listReviews(query: ReviewQuery = {}): Promise<ReviewItem[]> {
  const res = await request<{ items: ReviewItem[] }>({
    domain: DOMAIN,
    path: `/api/reviews${qs({ status: query.status === 'all' ? undefined : query.status || 'pending', from: query.from, to: query.to })}`,
    mock: async () => ({ items: await mockItems(query) }),
  });
  return res.items || [];
}

export async function getReview(id: string): Promise<ReviewDetail> {
  return request<ReviewDetail>({
    domain: DOMAIN,
    path: `/api/reviews/${encodeURIComponent(id)}`,
    mock: async () => {
      const [uid, date] = id.split(':');
      const all = await mockItems({ status: 'all', from: date, to: date });
      const item = all.find((i) => i.id === id);
      const employees = await listEmployees({ status: 'all' });
      const e = employees.find((x) => x.uid === uid);
      if (!item || !e) throw new ApiError('Tinjauan tidak ditemukan.', 404);
      return { ...item, segments: usageFor(e, date).segments };
    },
  });
}

export async function decideReview(
  id: string,
  decision: 'confirm' | 'reject',
  note: string,
): Promise<ReviewItem> {
  return request<ReviewItem>({
    domain: DOMAIN,
    method: 'POST',
    path: `/api/reviews/${encodeURIComponent(id)}/decision`,
    body: { decision, note: note || null },
    mock: async () => {
      db().reviewDecisions[id] = {
        status: decision === 'confirm' ? 'confirmed' : 'rejected',
        by: currentUsername(),
        at: Date.now() / 1000,
        note: note || null,
      };
      save();
      const [, date] = id.split(':');
      const all = await mockItems({ status: 'all', from: date, to: date });
      const item = all.find((i) => i.id === id);
      if (!item) throw new ApiError('Tinjauan tidak ditemukan.', 404);
      return item;
    },
  });
}

export async function countPendingReviews(): Promise<number> {
  try {
    return (await listReviews({ status: 'pending' })).length;
  } catch {
    return 0;
  }
}
