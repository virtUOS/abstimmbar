# Konzept — Abstimmbar (Audience-Response-System)

Funktionsumfang und fachliches Konzept für **Abstimmbar**, ein Open-Source
Audience-Response-System (ARS) für Hochschulen. Nachfolger des nativen
Stud.IP-Plugins **Cliqr**; funktional orientiert an **ARSnova/Particify**,
gestalterisch und technisch angelehnt an **Ausleihbar**.

> Sprachregelung: **Raum** (Veranstaltungskontext mit stabilem Code),
> **Fragenset** (Serie von Fragen), **Frage** (einzelnes Item mit
> Antwortformat), **Durchführung** (eine Live-Session eines Fragensets);
> Rollen **Lehrende**, **Teilnehmende**, **Admin**.
> Mit ⚠️ markierte Stellen sind Interpretationen, die noch zu bestätigen sind.

---

## 1. Leitidee

Lehrende erstellen Fragensets und führen sie live in der Lehrveranstaltung
durch (teacher-paced): Frage für Frage starten, stoppen, Ergebnisse als
Diagramm zeigen. Teilnehmende stimmen **anonym und ohne Login** auf dem
eigenen Gerät ab — Zugang per QR-Code, Kurz-URL oder Code-Eingabe auf der
Startseite. Das Tool ist eigenständig (kein LMS-Plugin) und wird per
**LTI 1.3 / LTI Advantage** in Lernmanagementsysteme (Stud.IP, Moodle, ILIAS,
…) eingebunden; Lehrende melden sich alternativ direkt per **OIDC** an.

**Derzeit kein Ziel:** Gamification à la Kahoot (Nicknames, Punkte,
Belohnung schneller Antworten, Ranglisten, Siegertreppchen) — bewusst
zurückgestellt; könnte zu einem späteren Zeitpunkt als optionales Feature
dazukommen.

## 2. Rollen

- **Teilnehmende** — brauchen keinen Account. Betreten einen Raum über
  QR-Code, Kurz-URL oder Code-Eingabe; stimmen anonym ab. Später optional:
  authentifizierte Teilnahme (OIDC bzw. LTI-Launch) für nicht-anonyme
  Umfragen und Wissensabfragen mit Rückmeldung ans LMS (AGS).
- **Lehrende** — erstellen und verwalten Räume und Fragensets, führen
  Durchführungen. Anmeldung per OIDC (Keycloak) oder LTI-Launch
  (Rolle `Instructor`).
- **Admin** — Instanzverwaltung: LTI-Plattform-Registrierungen,
  OIDC-Konfiguration, ggf. Nutzerverwaltung und Aufräumroutinen.

## 3. Domänenmodell

### 3.1 Begriffe und Beziehungen

- **Raum** — der Container, den Teilnehmende betreten. Hat einen **stabilen,
  menschenfreundlichen Code** (z. B. 8-stellig, wie Particify), eine daraus
  abgeleitete Kurz-URL und einen QR-Code. Der Code bleibt über alle
  Durchführungen hinweg gleich, damit Studierende ihn als Lesezeichen
  speichern können (Cliqr-Anforderung). Räume sind **wiederverwendbar**:
  derselbe Raum kann über Semester hinweg und für unterschiedliche Gruppen
  erneut genutzt werden. Ein Raum gehört einem oder mehreren
  Lehrenden und entspricht typischerweise einer Lehrveranstaltung; bei
  LTI-Einbindung ist er mit dem LMS-Kurskontext verknüpft.
- **Fragenset** — geordnete Serie von Fragen innerhalb eines Raums
  (Particify: „Fragenserie", Cliqr: „Fragenset"). Hat Titel und
  Beschreibung.
- **Abschnitt** *(optional, v2)* ✅ *(Juli 2026)* — benannte, geordnete
  Gruppe von Fragen innerhalb eines Fragensets (z. B. „Begrüßung",
  „Wiederholung", „Ende"). Flach, keine Verschachtelung; Fragen ohne
  Abschnitt sind weiterhin möglich. Im Präsentationsmodus erscheint beim
  ersten Betreten eines Abschnitts eine Zwischenfolie mit dem Namen.
- **Frage** — ein Item mit Fragentext (formatierbar, mit Bildern), einem
  **Antwortformat** (§4) und formatspezifischen Optionen.
- **Durchführung** — eine Live-Session eines Fragensets: Zustand pro Frage
  (nicht gestartet / offen / geschlossen / Ergebnisse sichtbar),
  eingegangene Stimmen, Zeitstempel. Ergebnisse hängen an der Durchführung,
  nicht an der Frage — so bleiben alte Ergebnisse beim erneuten Durchführen
  erhalten oder können gezielt gelöscht werden.
- **Stimme** — eine Antwort einer teilnehmenden Person auf eine Frage
  innerhalb einer Durchführung. Anonym; Mehrfachabstimmung wird per
  Teilnahme-Token (Session) verhindert, nicht per Account.

### 3.2 Mandanten

Wie Ausleihbar: **Single-Tenant, tenant-ready** — v1 läuft für eine
Einrichtung, die Modelle werden aber so entworfen, dass eine
Mandanten-Zuordnung später ergänzt werden kann. Bei LTI ist die
**Plattform-Registrierung** (issuer + client_id) ohnehin ein natürlicher
Mandanten-Anker.

## 4. Antwortformate

Orientiert an Particify/ARSnova, geschnitten in Stufen (Details zur
Reihenfolge in `docs/roadmap.md`):

| Format                      | Beschreibung                                                                                                                                                                                                | Stufe         |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| **Single Choice**           | genau eine Antwort wählbar; Antworten optional als richtig markierbar                                                                                                                                       | MVP           |
| **Multiple Choice**         | mehrere Antworten wählbar; richtige Antworten markierbar                                                                                                                                                    | MVP           |
| **Ja/Nein**                 | Sonderfall Single Choice mit festen Optionen                                                                                                                                                                | MVP (Vorlage) |
| **Likert-Skala**            | konfigurierbare Skala (z. B. 5 Stufen, Zustimmung)                                                                                                                                                          | v2            |
| **Offene Textantwort**      | Freitext, Anzeige als Liste ⚠️ (Moderation nötig?)                                                                                                                                                          | v2            |
| **Wortwolke**               | kurze Begriffe, aggregiert als Word Cloud; Begriffe, die sich nur in Groß-/Kleinschreibung unterscheiden, werden zusammengeführt ⚠️. Als spätere Zusatzoption: LLM-gestützte inhaltliche Zusammenfassung und Redundanz-Minimierung (Ausblick) | **MVP**       |
| **Priorisierung**           | Punkteverteilung auf Optionen                                                                                                                                                                               | Ausblick      |
| **Sortierung**              | gemischte Elemente per Drag & Drop (oder Pfeile) in die richtige Reihenfolge bringen; Auswertung als Positions-Genauigkeit je Element plus Quote „komplett richtig"                                       | v2            |
| **Matrix**                  | Zeilen × Spalten (z. B. Produkte × Eigenschaften); pro Zeile unabhängig mehrere Spalten ankreuzbar; Auswertung als Häufigkeit je Zelle (#4)                                                                | v2            |
| **Schätzfrage (numerisch)** | Zahl eingeben, Verteilung/Median anzeigen                                                                                                                                                                   | Ausblick      |
| **Slider**                  | Schieberegler für numerische Eingaben; Default 0–100 %, untere und obere Grenze konfigurierbar                                                                                                              | Ausblick      |

Gemeinsame Fragen-Optionen (formatabhängig):

- eine/mehrere Antworten als **richtig markieren** (optional — ohne
  Markierung ist es eine Umfrage ohne Wertung)
- **zufällige Reihenfolge** der Antwortoptionen bei der Präsentation
- **WYSIWYG-Editor** für Fragentexte: Formatierung (fett/kursiv/Listen),
  Bilder per Drag-and-drop platzierbar; bewusst schlanker Funktionsumfang
  (Bibliothekswahl → ADR-0007)
- ✅ *(Juli 2026)* Bilder auch als Antwortmöglichkeiten (v2)
- **Countdown-Timer** für die Beantwortungszeit (v2)
- Multiple Choice Distraktoren mit LLM erstellen (Ausblick)

## 5. Verwaltung (Lehrenden-Sicht)

### 5.1 Raum- und Fragenset-Übersicht

- Übersicht aller eigenen Räume; pro Raum die Fragensets in Tabellenform
  mit: Name, Erstellungsdatum, Datum der letzten Änderung, Anzahl der
  Fragen, Vorhandensein von Ergebnissen; auf-/absteigend sortierbar.
- **Volltextsuche** über Fragensets, einschließlich Fragen- und
  Antworttexten.
- Fragensets anlegen, umbenennen, löschen (mit Bestätigung), **duplizieren**
  und **in andere Räume kopieren** (insb. Vorsemester → neues Semester;
  ersetzt Cliqrs „Import aus früheren Veranstaltungen").
- Export/Import von Fragensets als Datei (JSON; ⚠️ Kompatibilität zu
  Particify-Export prüfen), Export von Ergebnissen als CSV.
- **Teilen & Zusammenarbeit** (v2) ✅ *(Juli 2026)*: Räume mit anderen
  registrierten Nutzenden teilen (**gemeinsames Editieren** — alle
  Mit-Besitzer:innen haben Vollzugriff auf Raum und Sets); Fragensets per
  **Kopier-Link** freigeben (nicht erratbares Token, widerrufbar; wer den
  Link hat und angemeldet ist, darf kopieren, nie bearbeiten). Optionale
  **Lizenz** pro Fragenset (CC-Auswahl), reist mit Kopien und Exporten.

### 5.2 Fragenset bearbeiten

- Titel und Beschreibung bearbeiten.
- Beliebig viele Fragen anlegen, löschen, **per Drag-and-drop umsortieren**.
- Fragen optional in **Abschnitte** gruppieren (§3.1): Abschnitte anlegen,
  benennen, umsortieren; Fragen per Drag-and-drop zwischen Abschnitten
  verschieben (v2).
- Fragen in andere Fragensets verschieben (v2).
- Pro Frage: letzte Ergebnisse als Balkendiagramm einsehen; Ergebnisse
  einzelner Durchführungen löschen.

### 5.3 Frage bearbeiten

- Fragentext mit Bildern; Antwortoptionen anlegen, löschen, umsortieren.
- Format- und Fragenoptionen gemäß §4.
- Neue Frage startet mit drei leeren Antwortfeldern (Cliqr-Szenario);
  weitere per Klick.

### 5.4 Automatische Übersetzung (Ausblick)

- Fragen und Antworten per **LibreTranslate**-API übersetzen — maschinelle
  Vorbefüllung, Kontrolle und Korrektur durch die Lehrperson (Mechanik wie
  bei Ausleihbar).
- Wortwolken: Zusammenführen gleichbedeutender Begriffe unterschiedlicher
  Sprachen per LLM.

## 6. Durchführung (Präsentieren)

### 6.1 Präsentationsmodus

Eigenständige, reduzierte Vollbild-Ansicht für den Beamer — enthält nur, was
für die Durchführung nötig ist, und ist **einbettbar** (iframe-fähig,
konfigurierbare `frame-ancestors`), damit später Präsentationssoftware sie
aufnehmen kann.

- **Startbildschirm**: Titel des Fragensets, QR-Code, Kurz-URL, Raum-Code,
  Zähler der verbundenen Teilnehmenden.
- Liegen zum Fragenset bereits Ergebnisse vor, fragt ein Dialog beim Start:
  Ergebnisse löschen (ja/nein/abbrechen); bei „nein" zählen neue Stimmen zur
  bestehenden Durchführung dazu (Cliqr-Verhalten).
- Ablauf pro Frage: **(1)** Frage aufrufen → **(2)** Beantwortung starten →
  **(3)** Beantwortung stoppen → **(4)** Ergebnisse zeigen. Erst mit dem
  Start wird die Frage für Teilnehmende sichtbar und beantwortbar
  (teacher-paced).
- Hat das Fragenset Abschnitte (§3.1), erscheint der Abschnittstitel beim
  Übergang als Zwischenfolie (v2).
- Live-Zähler der eingegangenen Stimmen pro Frage (Echtzeit).
- Ergebnisanzeige: Säulendiagramm mit absoluten Zahlen und Prozentwerten.
- Hervorhebung richtiger Antworten: **von der Lehrperson einstellbar** —
  *sofort* (mit der Ergebnisanzeige), *nach Ende der Befragung* (auf
  separaten Tastendruck) oder *nie*.
- **Tastaturkürzel**: Starten/Stoppen (`S`), Ergebnisse (`E`/`R`),
  nächste/vorige Frage (`→`/`←`), richtige Antwort zeigen (`A`, im Modus
  „nach Ende der Befragung").
- Präsentation beenden → zurück zur Fragenset-Verwaltung.

### 6.2 Teilnehmer-Ansicht

Ultraleichte, eigenständige Seite (eigenes, minimales Bundle — lädt schnell
auf Smartphones in vollem Hörsaal-WLAN):

- Zugangswege: QR-Code scannen, Kurz-URL anklicken, oder **Home-URL** der
  Instanz mit Code-Eingabefeld.
- Vor dem Start: Titel des Fragensets + Hinweis „noch nicht gestartet".
- Bei offener Frage: Fragentext und Antwortoptionen (konfigurierbar:
  alternativ nur A/B/C/… ohne Texte — für den Modus „Frage steht nur an der
  Wand"). Antwort antippen → Bestätigung; danach ist die Frage auf dem Gerät
  nicht mehr beantwortbar.
- Nach dem Stopp: Hinweis „Beantwortung geschlossen". Ergebnisse auch auf
  dem eigenen Gerät anzeigen: als Option der Durchführung ab **v2**.
- Kein Login, keine Datenerhebung über das Teilnahme-Token hinaus.

### 6.3 Self-paced-Modus (v2) ✅

Freigabe eines Fragensets als **Selbstlernquiz**: Teilnehmende beantworten
alle Fragen im eigenen Tempo, mit sofortiger Richtig/Falsch-Rückmeldung.
Umschaltbar zwischen teacher-paced und self-paced (Wunschkriterium Cliqr;
Particify: „Selbstlernmodus"). *Umgesetzt (Juli 2026):* Modus am
Durchlauf (`Run.mode`), Sofort-Feedback in der Antwort des Vote-Endpunkts
(unterdrückt bei „nie hervorheben"), eigener Quiz-Endpunkt mit
Wiederaufnahme nach Reload, Abschluss-Auswertung („x von y richtig"),
Lehrenden-Dashboard mit QR-Code und Antwortfortschritt pro Frage.
Countdown-Timer gelten bewusst nicht (eigenes Tempo ist der Zweck).

## 7. Ergebnisse & Auswertung

- Pro Frage und Durchführung: Balkendiagramm (identisch zur
  Präsentationsansicht) nachträglich abrufbar.
- Ergebnisse pro Fragenset/Durchführung löschbar (mit Bestätigungsdialog).
- Export als CSV (pro Fragenset: Fragen × Antwortoptionen × Stimmenzahl).
- Aggregation über Durchführungen hinweg: Ausblick ⚠️.

## 8. Integration

### 8.1 LTI 1.3 / LTI Advantage

- **Tool-Registrierung** pro Plattform (issuer, client_id, JWKS) über die
  Admin-Oberfläche; Dynamic Registration als Komfort-Ziel (v2).
- **Resource Link Launch**: Lehrende landen aus dem LMS-Kurs direkt in
  „ihrem" Raum (Kurskontext ↔ Raum-Verknüpfung wird beim ersten Launch
  angelegt). Rollen-Mapping: `Instructor` → Lehrende, `Learner` →
  authentifizierte Teilnahme ⚠️ (v1: Learner-Launch zeigt die
  Teilnehmer-Ansicht des Raums).
- **Deep Linking**: beim Einbinden im LMS ein Fragenset auswählen oder neu
  anlegen; der Link führt dann direkt dorthin.
- **NRPS** (Namen/Rollen) und **AGS** (Noten-Rückmeldung für Wissensabfragen
  und self-paced Quizze): v2/Ausblick — Datenmodell hält dafür die
  Verknüpfung Stimme ↔ LTI-Nutzer bereit, sobald nicht-anonyme
  Durchführungen existieren.
- **Kein LTI-1.1-Fallback.**

### 8.2 OIDC (Keycloak)

- Login für Lehrende/Admins direkt an der Instanz (ohne LMS-Umweg),
  wie Ausleihbar via `mozilla-django-oidc` inkl. Backchannel-Logout.
- Räume anlegen darf im Default **jede per OIDC angemeldete Person** —
  ausdrücklich auch Studierende (z. B. für Referate und Seminare). Später
  per Claims oder Gruppen einschränkbar (Mechanik wie Ausleihbars Access
  Groups).

### 8.3 Präsentationssoftware (Ausblick)

- **PowerPoint**: Office.js-Add-in, das Präsentations- und
  Ergebnis-Ansichten als Webview einbettet — möglich, weil beide Ansichten
  eigenständige URLs sind. Kein v1/v2-Ziel.
- **LibreOffice Impress**: kein Add-in-Modell; realistisch QR-Folie
  (exportierbares Folienbild mit QR + Kurz-URL) plus Browserfenster.

## 9. Datenschutz & Nicht-Funktionales

- **Anonymität by design**: Stimmen speichern kein Nutzerkonto, keine IP,
  kein Fingerprinting; Teilnahme-Token sind flüchtig (Session) und dienen
  nur der Mehrfachstimmen-Vermeidung. Nicht-anonyme Durchführungen (später)
  sind explizit gekennzeichnet — Teilnehmende sehen vor der Abgabe, dass
  ihre Antwort zugeordnet wird.
- **Skalierung**: Zielgröße ≥ 1000 gleichzeitige Teilnehmende pro Raum,
  mehrere parallele Durchführungen pro Instanz. Realtime per SSE
  (unidirektional), Stimmabgabe per POST.
- **Barrierefreiheit**: WCAG 2.1 AA / BITV-orientiert wie Ausleihbar —
  insbesondere die Teilnehmer-Ansicht (Screenreader, Tastatur, Kontrast).
- **Zweisprachigkeit** DE/EN für die UI; Inhalte (Fragen/Antworten) später
  per LibreTranslate übersetzbar (§5.4, Ausblick).
- **Gestaltung**: Design-Token und Komponenten-Idiom von Ausleihbar
  (Tailwind, ruhige Fläche, ein Akzent); Akzentfarbe für Abstimmbar: **Grün**
  (entschieden Juli 2026).
- **Lizenz**: Apache-2.0, Entwicklung öffentlich.

## 10. Abgrenzung (bewusst nicht)

- Kein vollwertiges Prüfungs-/Übungssystem (das ist Vips); Import aus Vips
  allenfalls als Ausblick.
- Kein natives LMS-Plugin; Stud.IP-Anbindung ausschließlich über LTI 1.3.
- Kein eigener Video-/Folien-Kanal — Abstimmbar ergänzt die Präsentation,
  ersetzt sie nicht.
