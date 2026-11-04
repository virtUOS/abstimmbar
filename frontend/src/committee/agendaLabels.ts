/** TOP numbers and vote labels of a meeting outline.
 *
 * Mirrors backend/committees/agenda.py: a section opens a TOP; a question
 * joins the open TOP when its `section` is that section, otherwise it is a
 * TOP of its own. A TOP with one vote labels it "3", with several "3a", "3b" …
 * `rows` must already be in outline order. */
export type AgendaRow =
  | { kind: "section"; id: number }
  | { kind: "question"; id: number; section: number | null };

/** 0 -> "a", 25 -> "z", 26 -> "aa" (bijective base 26). */
export function suffix(index: number): string {
  let out = "";
  let n = index + 1;
  while (n > 0) {
    const rem = (n - 1) % 26;
    out = String.fromCharCode(97 + rem) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

export function agendaLabels(rows: AgendaRow[]): {
  questions: Map<number, string>;
  sections: Map<number, number>;
} {
  const groups: { sectionId: number | null; questionIds: number[] }[] = [];
  let openSection: number | null = null;
  for (const row of rows) {
    if (row.kind === "section") {
      groups.push({ sectionId: row.id, questionIds: [] });
      openSection = row.id;
    } else if (openSection !== null && row.section === openSection) {
      groups[groups.length - 1].questionIds.push(row.id);
    } else {
      groups.push({ sectionId: null, questionIds: [row.id] });
      openSection = null;
    }
  }
  const questions = new Map<number, string>();
  const sections = new Map<number, number>();
  groups.forEach((group, i) => {
    const number = i + 1;
    if (group.sectionId !== null) sections.set(group.sectionId, number);
    if (group.questionIds.length === 1) {
      questions.set(group.questionIds[0], String(number));
    } else {
      group.questionIds.forEach((qid, j) => questions.set(qid, `${number}${suffix(j)}`));
    }
  });
  return { questions, sections };
}
