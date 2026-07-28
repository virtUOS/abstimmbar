# Roadmap & Implementierungsplan — Abstimmbar

Schneidet das Konzept (`docs/concept.md`) in lieferbare Stufen: **MVP**
(erste in der Lehre einsetzbare Version), **v2** und **Ausblick**, und
darunter in konkrete Meilensteine.

> Lebendiges Dokument. Bei Konflikten gewinnt das Konzept als Vision; die
> Roadmap sagt nur, *wann* etwas gebaut wird.

## Festgelegte Grundsatzentscheidungen

1. **Stack wie Ausleihbar** — Django 5 + DRF + PostgreSQL; React + Vite +
   TypeScript + Tailwind für die Verwaltungs-UI; bewusst minimale
   Dependency-Liste. → ADR-0001.
2. **Vier Frontend-Flächen, ein Backend** — Verwaltung (React, geschützt),
   Präsentationsmodus (Vollbild, einbettbar), Teilnehmer-Voting
   (eigenes, ultraleichtes Bundle), Home-URL mit Code-Eingabe. → ADR-0001.
3. **Realtime: SSE zuerst** — Stimmabgabe per POST, Push-Richtung
   (Fragenstatus, Live-Zähler) per Server-Sent Events; WebSockets nur, wenn
   SSE nachweislich nicht reicht. → ADR (offen).
4. **Anonyme Teilnahme by design** — kein Login für Teilnehmende,
   Mehrfachstimmen-Vermeidung per flüchtigem Teilnahme-Token. Login nur zum
   Erstellen; nicht-anonyme Durchführungen später als explizites Feature.
5. **LTI 1.3 / LTI Advantage, kein 1.1-Fallback** — via `pylti1p3`;
   Deep Linking im MVP-Umfang der LTI-Phase, NRPS/AGS später.
6. **Single-Tenant, tenant-ready** — wie Ausleihbar.

## MVP-Ziel (der durchgängige Loop)

> Eine lehrende Person meldet sich per OIDC an, legt einen Raum und ein
> Fragenset mit Choice-Fragen an und startet den Präsentationsmodus am
> Beamer. Studierende scannen den QR-Code und stimmen anonym auf dem Handy
> ab; die Lehrperson startet und stoppt jede Frage per Tastenkürzel, sieht
> den Live-Zähler und zeigt das Ergebnisdiagramm. Nach der Vorlesung schaut
> sie sich die Ergebnisse noch einmal an. Im nächsten Semester kopiert sie
> das Fragenset in den neuen Raum.

Wenn dieser Loop sauber funktioniert, kann Abstimmbar Cliqr in der Lehre
ersetzen. **LTI gehört bewusst nicht zum MVP-Loop** — der OIDC-Direktzugang
reicht für den Pilotbetrieb, und LTI folgt unmittelbar danach (M4), bevor
breiter ausgerollt wird.

## Meilensteine

### M0 — Fundament ✅ (Juli 2026)

- Repo-Gerüst nach Ausleihbar-Vorbild: Docker Compose (PostgreSQL 16,
  Keycloak, Backend, Frontend), Django-Projekt mit App-Schnitt
  (`accounts`, `polls` ⚠️ Namen per ADR), DRF, CI (Lint + Tests).
- OIDC-Login via Keycloak (Realm + Demo-Nutzer im Compose-Setup),
  Backchannel-Logout — von Ausleihbar übernehmen.
- Frontend-Gerüst: React + Vite + TS + Tailwind; Design-Token von
  Ausleihbar übernehmen, eigene Akzentfarbe.
- `CLAUDE.md`, ADR-Struktur, Lizenz/Notice.

### M1 — Verwalten (Fragensets & Fragen) ✅ (Juli 2026)

- Modelle + API: Raum (mit Code-Vergabe), Fragenset, Frage,
  Antwortoption.
- Verwaltungs-UI: Raum-Übersicht; Fragenset-Tabelle (Name, erstellt,
  geändert, #Fragen, Ergebnisse vorhanden; sortierbar); Fragenset anlegen/
  umbenennen/löschen; Fragen-Editor für Single/Multiple Choice mit
  Richtig-Markierung, Zufallsreihenfolge, Mehrfachauswahl;
  Drag-and-drop-Sortierung von Fragen und Antwortoptionen.
- **WYSIWYG-Editor** für Fragentexte (schlank, Bilder per Drag-and-drop;
  Bibliothekswahl → ADR-0007).
- **Wortwolken-Fragen** (Review-Entscheidung: im MVP; ohne LLM,
  Zusammenführung von Schreibvarianten bei Groß-/Kleinschreibung).
- Einstellung pro Frage/Fragenset, **wann richtige Antworten gezeigt
  werden**: sofort / nach Ende der Befragung / nie.
- Ja/Nein als Vorlage beim Anlegen.

### M2 — Durchführen (der Live-Loop) ✅ (Juli 2026)

- Modelle: Durchführung, Stimme, Teilnahme-Token.
- SSE-Kanal pro Raum (Fragenstatus, Zähler); Stimmabgabe-Endpoint mit
  Doppelstimmen-Schutz.
- Präsentationsmodus: Startbildschirm (QR, Kurz-URL, Code,
  Teilnehmer-Zähler), Frage starten/stoppen, Live-Stimmenzähler,
  Ergebnis-Säulendiagramm mit Prozentwerten bzw. **Live-Wortwolke**,
  Hervorhebung richtiger Antworten gemäß eingestelltem Modus,
  Tastaturkürzel, Beenden → Verwaltung.
- Teilnehmer-Ansicht als eigenes Mini-Bundle: Code-Eingabe (Home-URL),
  Warten aufs Start-Signal, Antworten, Bestätigung, „geschlossen"-Zustand.
- Dialog „Ergebnisse löschen?" beim Start mit vorhandenen Ergebnissen;
  „nein" → Stimmen zählen zur bestehenden Durchführung dazu.
- **Lasttest** (≥ 1000 simulierte Teilnehmende) gehört zu diesem
  Meilenstein, nicht ans Ende.
  - *Ergebnis (Juli 2026, `backend/scripts/loadtest.py`, Dev-Laptop):*
    1000 SSE-Verbindungen in 4,8 s aufgebaut; 1000 Stimmen in 4,6 s
    (215/s), 0 Fehler; Broadcast „Frage offen" erreichte alle 1000 Clients
    innerhalb von 118 ms. DB-Verbindungen per psycopg-Pool auf 20 gedeckelt
    (ADR-0003-Ergänzung).

### M3 — Auswerten & Wiederverwenden ✅ (Juli 2026)

- Ergebnisansicht in der Verwaltung (pro Frage/Durchführung), Ergebnisse
  löschen.
- Fragensets duplizieren und in andere Räume kopieren; Datei-Export/-Import
  (JSON); Ergebnis-Export (CSV).
- Volltextsuche über Fragensets, Fragen- und Antworttexte.

→ **Ende M3 = MVP ✅ (Juli 2026)**: bereit für Pilotbetrieb in echten
Vorlesungen (OIDC-Zugang). Bekannte v1-Einschränkung: Bilder im JSON-Export
referenzieren Instanz-lokale Media-URLs (Umzug auf andere Instanz verliert
Bilder; innerhalb der Instanz kein Problem).

### M4 — LTI 1.3 ✅ (Juli 2026)

- Tool-Registrierung (Django-Admin), Resource Link Launch mit Kurskontext ↔
  Raum-Verknüpfung, Rollen-Mapping (Lehrende → JIT-User + Owner; Lernende →
  anonym auf `/p/<code>/`), Deep Linking (Fragenset auswählen/anlegen).
  → ADR-0005, Anleitung in `docs/lti.md`.
- Verifiziert per Plattform-Simulator in der Test-Suite (signierte
  id_tokens, kompletter Handshake, Negativfälle). Manuelle Abnahme gegen
  echtes Moodle sowie gegen das Uni-Stud.IP (sobald dessen
  LTI-1.3-Consumer steht) steht noch aus ⚠️ — Anleitung in `docs/lti.md`.

### v2

- ✅ *(Juli 2026)* Weitere Antwortformate: **Likert** (5er-Skala-Vorlage,
  feste Reihenfolge, ohne Richtig-Markierung) und **offene Textantwort**
  (max. 500 Zeichen, Antwortliste). Likert-Ergebnisse als **divergierender
  Stapelbalken** (Ablehnung links, Zustimmung rechts, Neutral mittig;
  Prozente über die Skala, Enthaltungen separat) in Präsentation,
  Ergebnisseite und CSV.
- ✅ *(Juli 2026)* **Countdown-Timer** pro Frage (Sekunden, optional):
  Anzeige auf Beamer und Teilnehmer-Geräten, Auto-Stopp bei Ablauf,
  serverseitige Ablehnung verspäteter Stimmen.
- ✅ *(Juli 2026)* **Ergebnisse auf Teilnehmer-Geräten** (Option pro
  Fragenset): nur während der Ergebnis-Phase; richtige Antworten erst
  nach dem Reveal, das jetzt Server-Zustand ist (synchron zum Beamer).
- ✅ *(Juli 2026)* **Bilder als Antwortoptionen**: optionales Bild pro
  Antwort (Upload im Frage-Editor, gleiche Media-Ablage wie Bilder im
  Fragentext, nur instanz-eigene /media/-URLs); angezeigt auf Beamer,
  Teilnehmer-Geräten (live und Selbstlernquiz) und in den Ergebnissen;
  reist mit Kopien und Export/Import (Instanz-lokal, bekannte
  v1-Einschränkung wie bei Fragentext-Bildern).
- ✅ *(Juli 2026)* **Self-paced-Modus** (Selbstlernquiz) mit Umschalter:
  Start als „Selbstlernquiz" neben „Präsentieren" (derselbe unbeendete
  Durchlauf wechselt den Modus); Teilnehmende beantworten alle Fragen im
  eigenen Tempo mit sofortiger Richtig/Falsch-Rückmeldung (entfällt bei
  „nie hervorheben" und bei Fragen ohne markierte richtige Antwort),
  Abschluss-Auswertung und Wiederaufnahme nach Reload; Lehrende sehen
  ein Dashboard mit QR-Code und Antworten pro Frage.
- ✅ *(Juli 2026)* **Fragen zwischen Fragensets verschieben** (aus dem
  Frage-Editor heraus, ans Ende des Zielsets). Gesperrt, solange zur
  Frage Ergebnisse vorliegen — die hängen an den Durchführungen des
  Quellsets und würden sonst verwaisen.
- ✅ *(Juli 2026)* Optionale **Abschnitte** innerhalb von Fragensets:
  benannte Überschriften, die per „Abschnitte bearbeiten" (⋮-Menü) inline
  in die Fragenliste eingefügt werden; Zugehörigkeit ergibt sich aus der
  Position (Fragen per Drag-and-drop unter die passende Überschrift). Im
  Präsentationsmodus erscheint beim ersten Betreten eines Abschnitts eine
  **Zwischenfolie** mit dem Namen (Bestätigung per S/→). Fragen ohne
  Abschnitt bleiben möglich; Abschnitte reisen mit Kopien und
  Export/Import.
- ✅ *(Juli 2026)* **Teilen & Zusammenarbeit**: Räume lassen sich für
  Mit-Besitzer:innen freigeben (per Nutzerkennung/E-Mail, volles
  gemeinsames Bearbeiten; letzte besitzende Person geschützt); Fragensets
  bekommen optional einen Kopier-Link (nicht erratbares Token, jederzeit
  widerrufbar) mit optionaler CC-Lizenzangabe, die auch in Kopien und
  im JSON-Export mitreist. Gemeinsames Editieren = gemeinsamer
  Vollzugriff, kein Konflikt-Handling auf Feldebene (bewusst schlank).
- ✅ *(Juli 2026)* **Zweisprachigkeit DE/EN** (#33), Teil 1 — Oberfläche:
  React-Verwaltung und -Präsentation via i18next (englischer Quellstring =
  Schlüssel, `de/translation.json` mappt nach Deutsch), die framework-freie
  Teilnehmer-Seite via Django-gettext (`{% trans %}`, `LocaleMiddleware`,
  `?lang=`/Cookie/`Accept-Language`); Sprachumschalter im Nutzer-Menü bzw.
  als Globe-Menü, serverseitige Sprachpräferenz für angemeldete Nutzende.
  Teil 2 (Inhalts-Übersetzung autorierter Felder via django-modeltranslation
  + LibreTranslate) folgt als eigener MR.
- ✅ *(Juli 2026)* **Zweisprachigkeit DE/EN** (#33), Teil 2 — Inhalte:
  autorierte Felder (Raum-/Set-/Abschnitts-Titel, Beschreibungen, Frage- und
  Antworttext, Info-Seiten) mehrsprachig via `django-modeltranslation`
  (`*_de`/`*_en`-Spalten, kanonische Sprache `CONTENT_DEFAULT_LANGUAGE`).
  Übersetzte Felder werden überall als `{de,en}`-Map ausgeliefert (nötig, weil
  der SSE-Hub einen Payload an alle broadcastet) und clientseitig aufgelöst;
  der Editor bearbeitet Sprachen über Tabs mit optionaler LibreTranslate-
  Vorbefüllung (self-hostbar, per Default aus). Duplizieren/Export/Import
  sprachbewusst (Format v2, v1-kompatibel). CSV/KI arbeiten auf der
  kanonischen Sprache.
- ✅ *(Juli 2026)* **Fragetyp „Sortierung"** (#72): Teilnehmende bringen
  gemischte Elemente (Text/Bild) per Drag & Drop in die korrekte
  Reihenfolge (Pfeile als Tastatur-/Touch-Alternative); Auswertung als
  Positions-Genauigkeit je Element plus Quote „komplett richtig", auf
  Beamer, Ergebnisseite und im CSV-Export. Reist mit Kopien und
  Export/Import (die Autoren-Reihenfolge ist die Positionsspalte der
  Antwortoptionen selbst, kein separates Feld).
- LTI Dynamic Registration; NRPS.
- Nicht-anonyme Durchführungen (OIDC-/LTI-authentifizierte Teilnahme),
  als Grundlage für **AGS** (Noten-Rückmeldung ans LMS).

### Ausblick

- Priorisierung, Schätzfragen, **Slider** (numerisch, Default 0–100 %,
  Grenzen konfigurierbar).
- **LLM-Zusatzfunktionen** (jeweils optional): Wortwolken inhaltlich
  zusammenfassen/Redundanzen minimieren, Wortwolken sprachübergreifend
  zusammenführen, Multiple-Choice-Distraktoren generieren.
- Automatische Übersetzung von Fragen/Antworten per **LibreTranslate**
  (Mechanik wie Ausleihbar).
- PowerPoint-Add-in (Office.js); QR-Folien-Export für LibreOffice.
- Vips-Import; Aggregation über Durchführungen; Mandantenfähigkeit.
- Optionale Gamification (bewusst zurückgestellt, siehe Konzept §1).

## Geplante ADRs

| Nr.  | Thema                                                     | Status    |
| ---- | --------------------------------------------------------- | --------- |
| 0001 | Tech-Stack (Python/Django vs. Go; React vs. Vanilla)      | entworfen |
| 0002 | App-/Modul-Schnitt und Domänenbegriffe (EN-Namen)         | offen     |
| 0003 | Realtime-Transport (SSE vs. WebSockets/Channels)          | offen     |
| 0004 | Teilnahme-Token & Doppelstimmen-Schutz                    | offen     |
| 0005 | LTI-Integration (pylti1p3, Kontext-Mapping, Key-Handling) | akzeptiert |
| 0006 | Raum-Codes & Kurz-URLs (Format, Kollisionen, Lebensdauer) | offen     |
| 0007 | WYSIWYG-Editor (TipTap) & DnD (dnd-kit)                   | akzeptiert |

## Review-Entscheidungen (Juli 2026)

Die sechs offenen Fragen des ersten Entwurfs sind entschieden und in
Konzept und Roadmap eingearbeitet:

1. **Raum-Modell bestätigt** — stabiler Code pro Raum; Räume sind über
   Semester und für unterschiedliche Gruppen wiederverwendbar.
2. **Richtige Antworten**: von der Lehrperson einstellbar — sofort / nach
   Ende der Befragung / nie.
3. **Ergebnisse auf Teilnehmer-Geräten**: v2.
4. **Fragen-Editor**: WYSIWYG (schlank, Bilder per Drag-and-drop)
   → ADR-0007.
5. **Räume anlegen**: im Default alle per OIDC Angemeldeten (auch
   Studierende); später per Claims/Gruppen einschränkbar (wie Ausleihbar).
6. **Wortwolke im MVP** — ohne LLM; Schreibvarianten
   (Groß-/Kleinschreibung) werden zusammengeführt.

Außerdem ergänzt: Teilen & Zusammenarbeit inkl. Lizenzangabe (v2 ⚠️),
Bilder als Antwortoptionen (v2), Slider-Format, LLM-Zusatzfunktionen,
LibreTranslate-Übersetzung (alle Ausblick); Gamification von „nie" zu
„bewusst zurückgestellt" abgeschwächt.

## Noch offene Punkte

1. ~~**Teilen & Zusammenarbeit**~~ ✅ umgesetzt (Juli 2026): gemeinsames
   Editieren als gemeinsamer Vollzugriff ohne Konflikt-Handling auf
   Feldebene — bei Bedarf später verfeinerbar.
2. **Wortwolke, Schreibvarianten** ⚠️ Interpretation bestätigen: Begriffe,
   die sich nur in Groß-/Kleinschreibung unterscheiden, zählen als *ein*
   Begriff (angezeigt wird die häufigste Schreibweise) — oder war strikte
   Unterscheidung gemeint?
3. Moderation offener Textantworten (v2): nötig, optional, oder ohne?
4. ~~Akzentfarbe/Erscheinungsbild~~ → entschieden: **Grün** als Akzent
   (Juli 2026), Design-Token-Struktur von Ausleihbar.
