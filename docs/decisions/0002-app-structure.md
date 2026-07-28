# ADR-0002: App-Schnitt und Domänenbegriffe

- Status: **akzeptiert**
- Datum: 2026-07-06

## Kontext

Das Konzept (`docs/concept.md`) benennt die Domäne auf Deutsch (Raum,
Fragenset, Abschnitt, Frage, Durchführung, Stimme). Der Code ist englisch
(CLAUDE.md-Sprachregelung). Für M0 muss der Django-App-Schnitt stehen, damit
Migrationen und Importpfade stabil bleiben.

## Entscheidung

### Django-Apps

| App        | Verantwortung |
| ---------- | ------------- |
| `common`   | geteilte abstrakte Basismodelle (Zeitstempel), Hilfsfunktionen |
| `accounts` | Custom `User`, OIDC-Integration (Backend, Backchannel-Logout), whoami |
| `rooms`    | Autorenseite: `Room`, `QuestionSet`, `Section`, `Question`, `AnswerOption` |
| `live`     | Durchführung: `Run`, `Vote`, `ParticipantToken`, SSE-Kanal, Stimmabgabe |
| `lti`      | (ab M4) LTI-1.3-Plattformregistrierung, Launch, Deep Linking |

`rooms` und `live` sind bewusst getrennt: `rooms` ist klassisches CRUD mit
Besitzrechten, `live` ist der heiße Pfad (anonyme Teilnahme, Realtime,
Lasttest-Ziel) mit eigenem Sicherheits- und Performance-Profil. Die Grenze
entspricht der ADR-0001-Überlegung, den SSE-Fanout notfalls später als
eigenen Dienst herauslösen zu können.

### Domänenbegriffe DE → EN

| Konzept (DE)     | Code (EN)          |
| ---------------- | ------------------ |
| Raum             | `Room`             |
| Raum-Code        | `Room.code`        |
| Fragenset        | `QuestionSet`      |
| Abschnitt        | `Section`          |
| Frage            | `Question`         |
| Antwortoption    | `AnswerOption`     |
| Durchführung     | `Run`              |
| Stimme           | `Vote`             |
| Teilnahme-Token  | `ParticipantToken` |
| Lehrende (Rolle) | room owner/editor  |
| Teilnehmende     | participant        |

## Konsequenzen

- `AUTH_USER_MODEL = "accounts.User"` von der ersten Migration an
  (wie Ausleihbar, ADR-0002 dort).
- `rooms` importiert nie aus `live`; `live` referenziert `rooms`-Modelle
  per FK. `lti` hängt an `rooms` (Kurskontext ↔ Room) und `accounts`.
- UI-Texte übersetzen die EN-Modellnamen zurück ins Deutsche („Raum",
  „Fragenset") — Nutzersicht bleibt deutschsprachig konsistent.
