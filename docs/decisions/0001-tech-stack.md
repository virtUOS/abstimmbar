# ADR-0001: Tech-Stack — Django/DRF-Backend, React-Frontend mit schlanker Teilnehmer-Ansicht

- Status: **entworfen** (zur Diskussion, insb. mit den Go-Befürwortern)
- Datum: 2026-07-06

## Kontext

Abstimmbar ist ein neues Open-Source-ARS für Hochschulen (Konzept in
`docs/concept.md`). Zwei Stack-Fragen waren offen:

1. **Backend: Python (wie Ausleihbar) oder Go?** — Go wurde von Kollegen
   wegen Performance/Concurrency für die Realtime-Anteile ins Spiel gebracht.
2. **Frontend: React oder dependency-freies Vanilla-JS?** — These: bei
   KI-gestützter Entwicklung sei selbstgeschriebener Code ohne Dependencies
   langfristig wartbarer als ein Framework, dessen Abhängigkeiten veralten.

Rahmenbedingungen: dieselbe Organisation (virtUOS) entwickelt und betreibt
bereits **Ausleihbar** (Django 5 + DRF + PostgreSQL, React + Vite + TS +
Tailwind, OIDC via Keycloak/`mozilla-django-oidc`, Docker Compose). Der
kritische Integrationspfad von Abstimmbar ist **LTI 1.3 / LTI Advantage**.
Zielskala Realtime: ≥ 1000 gleichzeitige Teilnehmende pro Raum.

## Entscheidung

**Backend: Django 5 + Django REST Framework + PostgreSQL** — derselbe Stack
wie Ausleihbar. Realtime zunächst per **SSE** (async Django-Views);
Stimmabgabe als normaler POST.

**Frontend: React + Vite + TypeScript + Tailwind** für die Verwaltungs-UI
und den Präsentationsmodus — mit **rigoros minimaler Dependency-Liste**
(React, Vite, Tailwind, ggf. TanStack Query; keine UI-Kit-Bibliothek,
Komponenten selbst gebaut wie in Ausleihbar). Die **Teilnehmer-Ansicht** ist
ein eigenes, ultraleichtes Bundle, dessen Größe budgetiert wird
(Richtwert ⚠️: < 50 kB gzipped).

## Begründung

### Warum nicht Go

- **LTI 1.3 ist der kritische Pfad, nicht Realtime.** Für Python existiert
  mit `pylti1p3` eine gepflegte, verbreitete Bibliothek (Launch, Deep
  Linking, NRPS, AGS) inkl. Django-Support. Das Go-Ökosystem für LTI ist
  dünn; wir müssten einen sicherheitskritischen OIDC/JWT-Handshake
  weitgehend selbst implementieren und pflegen.
- **Die Realtime-Anforderung ist klein.** Eine Vorlesung = 10²–10³
  SSE-Verbindungen; uniweit wenige 10³. Das ist für async Django (uvicorn)
  unkritisch. Go's Stärken würden erst deutlich jenseits dieser Skala
  relevant.
- **Organisatorische Konsistenz.** Gelöste Muster aus Ausleihbar (OIDC inkl.
  Backchannel-Logout, Rollen, Compose-Setup, i18n DE/EN, ADR-Prozess)
  lassen sich direkt übernehmen; dieselben Personen können beide Systeme
  warten. Ein Zweit-Stack verdoppelt Betriebs- und Einarbeitungswissen.
- Der Großteil der Anwendung ist CRUD mit Rechteverwaltung — Djangos
  Kernkompetenz.

### Warum React statt „ohne Dependencies"

- **KI-Modelle sind bei React am stärksten**, nicht am schwächsten: es ist
  das am besten in Trainingsdaten repräsentierte Frontend-Idiom. Ein
  hausgemachtes Mini-Framework müsste jede KI-Session und jede neue Person
  erst ohne Doku lernen — man tauscht dokumentierte Konventionen gegen
  undokumentierte.
- **Bei App-Größe reinventiert man sonst das Framework.** Tabellen mit
  Sortierung, Drag-and-drop, Editor, Live-Diagramme sind genug Zustand,
  dass ohne Framework ein eigenes entsteht — nur schlechter getestet. Die
  Wartungslast verschwindet nicht, sie wandert von `npm update` in eigenen
  Code.
- **Churn begrenzt man über Disziplin:** React selbst ist stabil; schmerzhaft
  ist der lange Schwanz kleiner Abhängigkeiten. Deshalb: harte
  Dependency-Diät, keine UI-Kits, jede neue Dependency braucht eine
  Begründung im PR.
- **Wo die Vanilla-Intuition recht hat:** die Teilnehmer-Seite. Sie ist so
  klein (Frage anzeigen, antippen, SSE), dass sie als eigenes Mini-Bundle
  gebaut wird — ob Preact oder handgeschrieben ist dann zweitrangig; sie
  darf die Verwaltungs-App nicht mitladen.

### Realtime: SSE vor WebSockets

Die Push-Richtung ist rein unidirektional (Fragenstatus, Zähler);
Teilnehmer-Aktionen sind seltene POSTs. SSE ist einfacher zu betreiben
(HTTP, proxy-freundlich, Auto-Reconnect) und erspart zunächst
Channels/Redis-Infrastruktur. Wechsel auf WebSockets nur bei nachgewiesenem
Bedarf (→ ADR-0003, dort auch Lasttest-Ergebnisse aus M2).

## Konsequenzen

- Synergie mit Ausleihbar bei Auth, Deployment, Design-Token, i18n; geteiltes
  Betriebswissen.
- Python-Performance ist bei extremer Skalierung (mehrere große Unis auf
  einer Instanz) die erste Stelle, die man messen muss — Lasttest ist
  deshalb Teil von M2, nicht Nacharbeit.
- Die Dependency-Diät ist Policy: neue Frontend-Dependencies nur mit
  Begründung; jährlicher Update-Sweep eingeplant.
- Go bleibt Option für isolierte Spezialdienste (z. B. ein reiner
  SSE-Fanout-Dienst), falls der Lasttest das je erfordert — die API-Grenze
  Backend ↔ SSE-Kanal wird so geschnitten, dass das möglich bliebe.
