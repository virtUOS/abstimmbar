# ADR-0007: WYSIWYG-Editor (TipTap) und Drag-and-drop (dnd-kit)

- Status: **akzeptiert**
- Datum: 2026-07-06

## Kontext

Review-Entscheidung (Juli 2026): Fragentexte werden mit einem **schlanken
WYSIWYG-Editor** bearbeitet (Formatierung, Bilder per Drag-and-drop). Außerdem
verlangt M1 Drag-and-drop-Sortierung von Fragen und Antwortoptionen. Beides
selbst zu bauen widerspräche keinem Dependency-Diät-Ziel so sehr wie es die
Qualität gefährdete: contenteditable-Verhalten und barrierefreies DnD sind
notorisch fehlerträchtig. ADR-0001 verlangt für jede neue Dependency eine
Begründung — das ist diese.

## Entscheidung

1. **TipTap** (`@tiptap/react`, `@tiptap/starter-kit`,
   `@tiptap/extension-image`) als Editor. Headless (bringt kein eigenes
   UI-Kit mit — Toolbar bauen wir selbst mit Tailwind, passend zum
   Ausleihbar-Idiom), auf ProseMirror aufgebaut (seit Jahren gepflegter
   De-facto-Standard), MIT-lizenziert. Aktivierter Funktionsumfang bewusst
   klein: fett, kursiv, Listen, Bild. Erweiterungen nur per neuem Beschluss.
2. **dnd-kit** (`@dnd-kit/core`, `@dnd-kit/sortable`, `@dnd-kit/utilities`)
   für Sortierlisten. Zugänglich (Tastatur-Sortierung, Screenreader-
   Ankündigungen eingebaut), ohne Peer-Abhängigkeiten, MIT.
3. **Serverseitiges Sanitizing bleibt die Sicherheitsgrenze**: Der Editor
   liefert HTML, das Backend filtert es mit `nh3` (Rust-basiertes
   ammonia-Binding) auf eine Positivliste (p, br, strong, em, u, s, ul, ol,
   li, img[src|alt]). Was der Client schickt, ist nie vertrauenswürdig.

## Konsequenzen

- Frontend-Dependency-Zahl steigt um zwei Cluster; beide sind headless und
  ersetzbar, das UI bleibt unser eigenes.
- Bild-Upload braucht einen Backend-Endpoint (`/api/images/`) mit
  Pillow-Validierung; Bilder liegen im Media-Storage, nicht base64 im Text.
- Die Positivliste des Sanitizers ist die einzige Stelle, die bestimmt, was
  an Formatierung „durchkommt" — Editor-Erweiterungen ohne
  Sanitizer-Anpassung sind wirkungslos (gewollt).
