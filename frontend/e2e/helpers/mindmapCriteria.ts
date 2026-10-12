/** Mind map with AI colouring by criteria, seeded for the e2e checks.
 *
 *  The classification itself is an LLM call in the backend's background
 *  loop — not something a test can (or should) wait for. So the room, run and
 *  terms go through the REST API as usual, and the stored assignments
 *  (`MindmapNode.ai_criterion` + criteria fingerprint + text key) and the
 *  persisted colouring switch (`MindmapPhase.ai_criteria_active`) are
 *  written directly via `manage.py shell` in the backend container — exactly
 *  what a finished classification pass leaves behind. No LLM is involved;
 *  nothing changes the tree afterwards, so no pass is scheduled either.
 *  Needs the dev stack (`docker compose up -d`) like every e2e spec. */
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { APIRequestContext } from '@playwright/test';
import { API_BASE_URL, csrfToken } from '../fixtures';
import {
  apiClient,
  control,
  createRoomWithQuestions,
  joinParticipants,
  LONG_WORD,
  startRun,
} from './seed';

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');

export const CRITERIA = [
  { de: 'Orte', en: 'Places' },
  { de: 'Einrichtungen', en: 'Facilities' },
  { de: 'Themen', en: 'Topics' },
];

/** Term → criterion index (null = "no criterion fits"), parent term or null. */
const TERMS: { text: string; parent: string | null; criterion: number | null }[] = [
  { text: 'Osnabrück', parent: null, criterion: 0 },
  { text: 'Mensa', parent: null, criterion: 1 },
  { text: 'Digitalisierung und Infrastruktur', parent: null, criterion: 2 },
  { text: LONG_WORD, parent: null, criterion: null },
  { text: 'Westerberg', parent: 'Osnabrück', criterion: 0 },
  { text: 'Bibliothek', parent: 'Mensa', criterion: 1 },
];

/** Write stored classifications + switch the colouring on (see above). */
export function seedClassification(runId: number, questionId: number): void {
  const assign = Object.fromEntries(TERMS.map((t) => [t.text, t.criterion]));
  const code = `
import json
from live.models import MindmapNode, MindmapPhase, Run
from rooms.mindmap import criteria_fingerprint
from rooms.models import Question
run = Run.objects.get(pk=${runId})
q = Question.objects.get(pk=${questionId})
fp = criteria_fingerprint(q.mindmap_criteria)
assign = json.loads(${JSON.stringify(JSON.stringify(assign))})
for n in MindmapNode.objects.filter(run=run, question=q):
    n.ai_criterion = assign.get(n.text)
    n.ai_criteria_fp = fp
    n.ai_text_key = n.text_key
    n.save(update_fields=["ai_criterion", "ai_criteria_fp", "ai_text_key"])
MindmapPhase.objects.update_or_create(run=run, question=q, defaults={"ai_criteria_active": True})
`;
  execFileSync(
    'docker',
    ['compose', 'exec', '-T', 'backend', 'python', 'manage.py', 'shell', '-c', code],
    { cwd: REPO_ROOT, stdio: 'pipe' },
  );
}

/** A room with one mind map (no rating phase, AI switch on, three
 *  criteria), a live run with the terms above added by participants, the
 *  classification seeded and the results phase shown. */
export async function seedCriteriaMindmap(
  request: APIRequestContext,
  label: string,
  onRoomCreated: (roomId: number) => void,
): Promise<{ code: string; setId: number; runId: number; questionId: number }> {
  const room = await createRoomWithQuestions(request, ['mindmap'], label, onRoomCreated);
  const api = apiClient(request);
  const questionId = room.questions[0].id;
  const token = await csrfToken(request);
  const patch = await request.fetch(`${API_BASE_URL}/api/questions/${questionId}/`, {
    method: 'PATCH',
    headers: token ? { 'X-CSRFToken': token } : undefined,
    data: { mindmap_rating_mode: '', wordcloud_ai_enabled: true, mindmap_criteria: CRITERIA },
  });
  if (!patch.ok()) throw new Error(`PATCH question → ${patch.status()}: ${await patch.text()}`);
  const runId = await startRun(api, room.setId);
  await control(api, runId, 'open', questionId);
  const [participant] = await joinParticipants(request, room.code, 1);
  const ids = new Map<string, number>();
  for (const term of TERMS) {
    const r = await request.post(`${API_BASE_URL}/api/live/rooms/${room.code}/mindmap/add/`, {
      data: {
        token: participant,
        question: questionId,
        parent: term.parent ? ids.get(term.parent) : null,
        text: term.text,
      },
      headers: token ? { 'X-CSRFToken': token } : undefined,
    });
    if (!r.ok()) throw new Error(`mindmap add ${term.text} → ${r.status()}: ${await r.text()}`);
    ids.set(term.text, (await r.json()).node_id);
  }
  seedClassification(runId, questionId);
  await control(api, runId, 'results', questionId);
  return { code: room.code, setId: room.setId, runId, questionId };
}
