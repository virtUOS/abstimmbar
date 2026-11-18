# Changelog

Alle nennenswerten Änderungen an Abstimmbar stehen in dieser Datei. Das Format
folgt [Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die
Versionsnummern folgen [Semantic Versioning](https://semver.org/lang/de/).
Die Zahlen in Klammern verweisen auf Pull Requests im
[GitHub-Repository](https://github.com/virtUOS/abstimmbar/pulls?q=is%3Apr).

## [Unreleased]

> ### Hinweise für den Betrieb
>
> - **Caddy leitet `/g/*` an Django weiter.** Unter `/g/<token>/` liegen die
>   persönlichen Sitzungslinks der Gremienmitglieder. Die mitgelieferte
>   Caddyfile enthält die Weiterleitung bereits; wer die Caddyfile angepasst
>   hat oder einen eigenen Reverse-Proxy betreibt, muss `/g/*` ergänzen
>   (Liste der weiterzuleitenden Pfade in der Installationsanleitung).

### Hinzugefügt

- Gremien-Raum (Teil 1): Raumtyp für Gremien mit Statusgruppen, Mitgliedern,
  Stellvertretungen und Beobachtergruppe; Sitzungen mit Termin, persönlichen
  Links und Vertretungen. Abstimmen folgt.
- Gremien-Raum: Wahlen mit mehreren Stimmen, Kumulieren und Stichwahl.
- KI-Freitextauswertung: Jede Antwort zeigt ihre Einstufung farbig
  (Präsentation unter „Original“ mit Legende, Ergebnisse nach Kategorie
  gruppiert); die Vorlage *Stimmung* hat die Kategorie „gemischt“ für
  Antworten mit Lob und Kritik. Unsichere Antworten landen weiterhin bei
  „neutral“/„unklar“ (#291).
- Gremien-Raum: persönliche Sitzungslinks per E-Mail verschicken (optional, SMTP).
- Gremien-Raum: Übersetzungen des Beschlusstexts werden erst nach
  Bestätigung durch die Sitzungsleitung angezeigt; optionales
  KI-Korrekturlesen; Tastaturfokus bleibt in Dialogen.

### Geändert

- Oberfläche: React 19 und Vite 8 (vorher React 18 und Vite 6).
- Plattform: Django 6.1 (vorher 5.2 LTS). Der Mailversand nutzt die neue
  `MAILERS`-Konfiguration von Django; die Umgebungsvariablen `EMAIL_*`
  bleiben unverändert Ein anderes Backend als SMTP (z. B. das
  Konsolen-Backend der Entwicklungsumgebung) erhält keine SMTP-Optionen mehr,
  die Django 6.1 sonst ablehnt.
- Der JSON-Export eines Fragensets enthält jetzt die hochgeladenen Bilder
  (Fragetext, Beschreibungen, Antwortbilder). Beim Import, etwa auf einer
  anderen Instanz, werden sie wie ein Upload geprüft und neu gespeichert;
  ungültige Bilder werden übersprungen. Ältere Exportdateien lassen sich
  weiter importieren. Importdateien dürfen dafür bis zu 32 MiB groß sein
  (bisher 10 MiB) (#290).
- Der Prometheus-Endpunkt `/metrics` nutzt jetzt den gemeinsamen Baustein
  aus basicbar-integrations 0.4.0. Kennzahlen, Token und Statuscodes bleiben
  gleich; Antworten tragen zusätzlich `Cache-Control: no-store`.
- Der PDF-Rahmen des Sitzungsprotokolls (Schrift, Fußzeile, Editor-HTML)
  kommt jetzt aus dem gemeinsamen Paket basicbar-pdf 0.1.0; das PDF sieht
  unverändert aus.
- „Aus Dokument“ liest Folien und Seiten jetzt strukturiert: Folien- bzw.
  Seitengrenzen und Zeilenumbrüche bleiben erhalten, Tabellen kommen
  zeilenweise, Diagramme mit Titel und Werten, Sprechernotizen gekennzeichnet
  (PPTX auch aus gruppierten Formen). Die KI kann so Fragen zu konkreten
  Tabellen- und Diagrammwerten und zu Notizen stellen (#305).
- „Aus Dokument“ verteilt die Fragen gleichmäßig über die Folien bzw.
  Seiten: Jede inhaltliche Folie bekommt ihren Anteil, fast leere Folien wie
  die Titelfolie keinen; die gewünschte Anzahl wird genau angefragt und bei
  Bedarf nachgefordert. Jeder Vorschlag zeigt, auf welche Folie bzw. Seite er
  sich bezieht (#304).
- „Aus Dokument“: Die „Zusätzlichen Vorgaben“ sind jetzt verbindlich. Sie
  stehen im Auftrag an die KI direkt nach dem Material und haben Vorrang vor
  Fragetyp-Verteilung und Frageniveau, z. B. für Fragen zu konkreten Zahlen
  (#306).
- „Aus Dokument“: Nicht ausgewählte Vorschläge bleiben nach „Ausgewählte
  übernehmen“ erhalten. Der Hinweis im Fragenset zeigt, wie viele noch auf
  Prüfung warten; erst „Rest verwerfen“ oder das Übernehmen des letzten
  Vorschlags schließt die Erzeugung ab (#292).
- Lösch-Rückfragen nennen jetzt, was gelöscht wird, z. B. „Fragenset
  „Testset (2)“ löschen?“; das gilt auch für Räume und Sitzungen. Abschnitte
  werden nicht mehr beim ersten Klick gelöscht, sondern nach einer Rückfrage
  mit Namen (#288).
- Ergebnisse auf dem eigenen Gerät: Liegen noch keine Antworten vor (z. B.
  eine Wortwolke ohne Begriffe), zeigen die Geräte wie der Beamer „Noch keine
  Begriffe …“ bzw. „Noch keine Antworten …“ statt nur des Fragetexts (#287).
- Wortwolke und Freitext am Beamer: Auch im Modus „Einfach“ lassen sich
  unpassende Begriffe bzw. Antworten mit × ausblenden und über den Stift
  wieder einblenden. Zusammenführen, Umbenennen und KI-Ansichten bleiben dem
  Modus „Experte“ vorbehalten (#297).
- Freitext-Antworten und KI-Kernaussagen erscheinen am Beamer, auf der
  Ergebnisseite und auf den Geräten in einer einheitlichen, neutralen
  Kärtchenfarbe. Die bisherigen wechselnden Farben hatten keine Bedeutung,
  wirkten aber wie Kategorien; farbig bleiben nur die benannten Gruppen der
  Ansicht „Gruppiert“ und die Bewertungsbalken (#295).
- Präsentation: Wer bei laufender Abstimmung die Ergebnisse oder die Lösung
  einblendet, wird vorher gefragt, weil das die Abstimmung beendet
  (Abbrechen / „Abstimmung beenden und Ergebnisse zeigen“, für die
  Präsentation abschaltbar); „Stoppen“ fragt nie nach (#289).

### Behoben

- Präsentation nach dem Abmelden (z. B. in einem anderen Tab): Bedienelemente
  scheiterten stumm, und nach dem Neuladen hing die Seite bei „Verbinde …“.
  Jetzt erscheint „Sie wurden abgemeldet. Bitte melden Sie sich erneut an.“
  mit einer Schaltfläche zur Anmeldung, die danach zur Präsentation
  zurückführt (#298).
- Präsentation: Unter dem QR-Code steht wieder die vollständige
  Teilnahme-Adresse samt Domain (z. B. `abstimmbar.example.org/p/…`) statt
  nur des Pfads `/p/…`; ebenso im Alternativtext des QR-Bildes (#322).

## [1.0.1] – 2026-11-17

Fehlerbehebungen aus der ersten Testrunde nach 1.0. Keine
Datenbankmigrationen.

> ### Hinweise für den Betrieb
>
> - **Caddy nach dem Update neu starten.** `up -d` übernimmt ein per
>   `git pull` geändertes `Caddyfile` nicht; Caddy lief dann mit alter
>   Konfiguration weiter, sodass z. B. die Vorschau im Frage-Editor und
>   Lernkontroll-Links eine Fehlerseite zeigten. Die Update-Anleitung enthält
>   dafür jetzt `docker compose -f docker-compose.prod.yml up -d
>   --force-recreate caddy`. Führen Sie den Befehl auch einmalig aus, wenn
>   Sie bisher ohne ihn aktualisiert haben (#299, #279).
> - **Optional:** `AI_GEN_PER_CALL` (Standard 5) legt fest, wie viele Fragen
>   „Fragen aus Dokument“ höchstens je KI-Anfrage erzeugt. Nur bei sehr
>   langsamen Modellen kleiner setzen (#309).

### Behoben

- Fragen aus Dokument: Bei etwa zehn oder mehr gewünschten Fragen entstanden
  oft gar keine, weil eine einzige KI-Anfrage alle Fragen liefern sollte und
  dabei an Zeit- oder Längengrenzen scheiterte. Die Fragen werden jetzt in
  mehreren kleineren Anfragen erzeugt (höchstens `AI_GEN_PER_CALL`, Standard
  5, je Anfrage), ohne Wiederholungen (#309).
- Fragen aus Dokument: Scheitert die Erzeugung, erscheint nicht mehr
  „0 Fragen wurden erzeugt – jetzt prüfen“, sondern eine verständliche
  Ursache (z. B. KI antwortet nicht rechtzeitig, KI-Dienst nicht erreichbar)
  und „Erneut versuchen“, das mit demselben Dokument und denselben
  Einstellungen neu startet, ohne erneutes Hochladen. Konnte nur für einen
  Teil des Dokuments nichts erzeugt werden, weist ein Hinweis darauf hin
  (#302).
- Fragen aus Dokument: Eine neue Erzeugung zeigte unter Umständen die
  Vorschläge des vorigen Durchlaufs an. Eine neue Erzeugung ersetzt jetzt
  ältere, noch nicht geprüfte Vorschläge des Sets, die Prüfansicht folgt
  immer dem aktuellen Durchlauf, und das Formular weist vor dem Start auf
  noch ungeprüfte Vorschläge hin (#303).
- Fragen aus Dokument: „Fragen pro Seite“ heißt jetzt „Fragen pro
  Dokumentseite bzw. Folie“. Der Hilfetext erklärt, dass bei eingefügtem
  Text je etwa 2000 Zeichen als eine Seite zählen, und zeigt die daraus
  folgende Fragenzahl (z. B. „3 Seiten × 2 = 6 Fragen“), ebenso der
  Fortschrittshinweis während der Erzeugung (#292).
- Freitext: Beim Wechsel zur nächsten Freitext-Frage stand die vorige
  Antwort noch im Eingabefeld und wurde unbemerkt mit abgeschickt (#277).
- Präsentation mit Abschnitten: Die Zwischenfolie erscheint jetzt an fester
  Stelle (vor- und zurückblättern), ein Sprung über die Fragenliste landet
  direkt auf der gewählten Frage, und beim Verlassen der Zwischenfolie blitzt
  nicht mehr kurz die vorherige Frage auf (#278).
- Lernkontrolle: „Link kopieren“ liefert den vollständigen Link samt Domain
  statt nur des Pfads (#279).
- Statt der Entwickler-Fehlerseite („Unexpected Application Error“) zeigt
  die Oberfläche bei unbekannten Adressen eine verständliche Fehlerseite;
  bei Adressen, die der Server bereitstellen müsste, mit einem Hinweis auf
  die Webserver-Konfiguration (#279, #299).
- Mehrere Tabs desselben Browsers zählen am Beamer nur einmal; ein zweiter
  Tab kennt die bereits abgegebenen Begriffe der Wortwolke (#286).
- Likert-Ergebnis auf Teilnehmergeräten: Der Marker „▲ Sie“ steht an der
  Skalenposition der gewählten Stufe (wie der ø-Strich) statt in der Mitte
  des eigenen Segments (#281).
- Likert: Die Bestätigung „Ihre Antwort:“ zeigt bei unbeschrifteten Stufen
  die Skalenposition (z. B. „4 von 5“) statt eines leeren Werts, auch in
  „Meine Antworten“ und nach dem Neuladen (#282).
- Quiz-Block: Sortierfragen erhalten bei aktivem Sofort-Feedback
  „Richtig/Falsch“ samt richtiger Reihenfolge und zählen in der persönlichen
  Auswertung mit (#283).
- Freitext: Zeilenumbrüche in Antworten bleiben in der Bestätigung für
  Teilnehmende, am Beamer und auf der Ergebnisseite erhalten (#294).
- Ergebnisse zeigen Dezimalzahlen und Prozente in der Schreibweise der
  Oberflächensprache, z. B. „66,7 %“ und „Ø 5,3“ statt „66.7%“ und „Ø 5.3“
  (#293).
- Bilder bis 20 MB (vorher 5 MB) lassen sich hochladen; sie werden wie
  bisher verkleinert gespeichert. Scheitert ein Bild-Upload, etwa weil die
  Datei zu groß ist, zeigt der Editor jetzt eine verständliche Meldung,
  auch bei Bildern an Antwortoptionen, die bisher kommentarlos fehlschlugen
  (#280).
- CSV-Export: Die Spalte `gestartet` zeigt die Ortszeit samt Abstand zu UTC
  (vorher UTC ohne Kennzeichnung, also eine Stunde zu früh), und `prozent`
  ist jetzt auch bei Einfach- und Mehrfachauswahl sowie Ja/Nein-Fragen
  gefüllt, mit denselben Anteilen wie in der Ergebnisansicht (#284).
- KI-Kurzbericht: Der Bericht gab die Zahl der Antworten als Zahl der
  Teilnehmenden aus („8 Teilnehmer“ bei 8 Antworten). Das Modell erhält
  jetzt beide Zahlen getrennt (#285).
- Wortwolke: Ausgeblendete und zusammengeführte Begriffe stehen in der
  Moderationsliste der Präsentation jetzt in der Schreibweise, in der sie
  auch in der Wolke erscheinen („Python“ statt „python“) (#296).
- Sprachmischung: Wer im selben Browser die Teilnahmeseite in einer anderen
  Sprache geöffnet hatte, bekam danach auch in der Verwaltung Meldungen des
  Servers in dieser Sprache. Angemeldete Personen erhalten jetzt die Sprache
  ihrer Oberfläche, und die Suche auf der Startseite zeigt
  Titel und Fragen in der Sprache der Oberfläche. In der Lernkontrolle
  begründet die KI ihre Bewertung von Freitextantworten in der Sprache der
  Teilnahmeseite statt immer auf Deutsch (#300).

### Sicherheit

- pypdf 6.21.1 → 6.21.4: behebt mehrere Fälle, in denen präparierte
  PDF-Dateien beim Folienimport Endlosschleifen oder sehr hohen
  Speicherverbrauch auslösen konnten (GitHub-Advisories vom 23. und
  30. Oktober 2026).

## [1.0.0] – 2026-10-22

Die erste stabile Version. Abstimmbar ist damit für den regulären Einsatz in
der Lehre freigegeben.

> ### Hinweise für den Betrieb
>
> Bitte lesen Sie diese Punkte vor dem Update einer bestehenden Installation.
> Die Anleitung „Bestehende Installation aktualisieren“ im
> Installationskapitel beschreibt den Ablauf Schritt für Schritt.
>
> - **OIDC-Abgleich per Benutzername ist jetzt standardmäßig aus.**
>   `OIDC_MATCH_BY_USERNAME_FALLBACK` war bisher an. Wenn Ihre Installation
>   darauf angewiesen ist (etwa weil der Identity Provider Subjects neu
>   vergibt), setzen Sie `OIDC_MATCH_BY_USERNAME_FALLBACK=1`. Auch dann
>   übernimmt der Abgleich nie Konten ohne OIDC-Subject, also weder lokale
>   Notfall-Administratorkonten noch LTI-Konten (basicbar-auth ≥ 0.2.2)
>   (#212, #213).
> - **Kein Start mit Platzhalter-Schlüssel.** Bei `DJANGO_DEBUG=0` verweigert
>   Abstimmbar den Start, wenn `DJANGO_SECRET_KEY` noch den Entwicklungs-
>   bzw. Beispielwert aus `.env.prod.example` trägt (fehlt der Schlüssel
>   ganz, bricht bereits Docker Compose ab). Erzeugen Sie vor dem Update
>   einen eigenen Schlüssel, z. B. mit `openssl rand -base64 48` (#212, #223).
> - **Caddyfile ohne lokale Anpassungen.** Domain, ACME-Kontakt und erlaubte
>   LMS-Origins für die Einbettung kommen jetzt aus `PUBLIC_BASE_URL`,
>   `ACME_EMAIL` und `ABSTIMMBAR_FRAME_ANCESTORS` (leer = nur die eigene
>   Seite; mehrere Origins durch Leerzeichen getrennt). Haben Sie die
>   Caddyfile bisher selbst angepasst, übertragen Sie die Werte in die `.env`
>   und setzen Sie die Datei mit `git checkout -- Caddyfile` zurück. Eigene
>   Zertifikate und die IP-Einschränkung für `/metrics` bleiben
>   dokumentierte Ausnahmen (#223).
> - **Caddy leitet `/c/*` an Django weiter.** Links und QR-Codes der
>   Lernkontrolle sowie die LTI-Weiterleitung für Lernende funktionieren
>   damit in der Standardkonfiguration. Wer einen eigenen Reverse-Proxy
>   betreibt, findet die Liste der weiterzuleitenden Pfade in der
>   Installationsanleitung (#212).
> - **Das Image startet uvicorn.** Der Standardbefehl des Images ist jetzt
>   uvicorn (ASGI) statt des Django-Entwicklungsservers; eigene
>   Compose-Dateien ohne ausdrückliches `command` erhalten damit die
>   Live-Übertragung zuverlässig (#212).
> - **Größere Uploads im JSON-Format.** `DATA_UPLOAD_MAX_MEMORY_SIZE` liegt
>   jetzt bei 10 MiB, damit auch große Fragenset-Importe angenommen werden;
>   größere Anfragen werden sauber abgelehnt (#214).
> - **Alte API-Teile entfernt:** der Endpunkt `reorder-sections` und der
>   Parameter `reset` beim Start einer Durchführung (siehe „Entfernt“)
>   (#216).
> - **Neue bzw. jetzt durchgereichte Variablen** in der Produktions-Compose:
>   `OIDC_MATCH_BY_USERNAME_FALLBACK`, `ACME_EMAIL`,
>   `ABSTIMMBAR_FRAME_ANCESTORS` (Caddy), `VITE_GUIDE_URL` und
>   `VITE_GUIDE_URL_EN` (Ziel des Menüpunkts „Anleitung“, wirken beim
>   Bauen des Images) (#210, #211, #212, #223).
> - **Plattform-Updates:** Django 5.2 LTS, Node 24, Pillow 12, pypdf 6,
>   react-router 7. Die Datenbank-Migrationen laufen beim Start
>   automatisch (#214, #220).

### Fragetypen

- Mindmap: Beim Ziehen eines Begriffs zeigen alle Begriffe ihre Lasche
  „Hier einhängen“; so lässt sich ein Begriff gezielt als Unterbegriff
  einhängen statt mit einem anderen zusammengeführt zu werden (#218).
- Mindmap: Zusammenführen, Verschieben, Umbenennen und übernommene
  KI-Vorschläge werden protokolliert und lassen sich einzeln zurücksetzen,
  auch nach einem Neuladen des Beamers (#209).
- Mindmap: Die Zahl der Stimmen berücksichtigt jetzt auch Teilnehmende, die
  nur bewertet haben (#215).
- Mindmap: Der Bewertungsmodus lässt sich nach Beginn der Bewertungsphase
  nicht mehr umstellen, wie bei der Vier-Felder-Matrix (#215).
- Frageneditor: Eingaben im Textfeld gehen bei langsamer Verbindung nicht
  mehr verloren, der Editor springt beim Laden nicht mehr, und beim
  schnellen Weiterklicken überschreiben veraltete Daten keine Änderungen
  mehr (#205, #206).
- Frageneditor: Zahlenfelder bei Mindmap und Wortwolke springen beim Leeren
  nicht mehr auf 1 (#215).

### Präsentation

- Mindmap und Vier-Felder-Matrix bleiben nach dem Ende der Abstimmung am
  Beamer sichtbar, auch wenn der Timer abgelaufen ist oder Sie die
  Präsentation verlassen und wieder betreten haben (#217).
- Der Zähler unten links ist jetzt eine Füllpille: Er zeigt Verbundene und
  Antwortende und bei Wortwolke, Mindmap und Matrix zusätzlich, wie viele
  Beiträge bzw. Punkte von der möglichen Gesamtzahl schon vergeben sind
  (#219).

### Oberfläche und Anleitung

- Neue Projekt-Website mit Anleitung für Lehrende und Installationsanleitung,
  auf Deutsch und Englisch: https://virtuos.github.io/abstimmbar/ (#210,
  #211).
- Der Menüpunkt „Anleitung“ im Hilfemenü öffnet die Anleitung in der
  Sprache der Oberfläche (#210, #211).
- Beim Umschalten zwischen einfachem und Experten-Modus erscheint ein
  kurzer Hinweis, und neu eingeblendete Bedienelemente werden kurz
  hervorgehoben (#222).
- Die Versionsnummer steht dezent in der Fußzeile und im Admin-Bereich
  (#224).
- App und Teilnahmeseite haben ein Favicon und ein Icon für den
  Startbildschirm von Smartphones (#221).
- Fehlermeldungen des Servers erscheinen durchgängig in der gewählten
  Sprache (#215).

### KI

- Vier-Felder-Matrix: Die KI schlägt vor, ähnliche Karten zu Sammelkarten
  zusammenzufassen (wählbar: nur Schreibweise, inhaltlich gleich,
  konzeptionell ähnlich). Sie prüfen jeden Vorschlag, können Titel und
  Kategorie anpassen und das Übernehmen rückgängig machen. An die KI gehen
  nur Karteninhalte, keine Daten über Teilnehmende (#207, #208).
- Fragen aus Dokumenten: Ist das Material ungeeignet, nennt die KI jetzt
  den Grund, statt einfach keine Fragen zu liefern (#216).
- Antworten in Aufzeichnungen werden jetzt ebenfalls von der KI bewertet
  und bleiben nicht mehr auf „wird bewertet“ stehen (#215).
- Auf der Ergebnisseite erscheinen KI-Funktionen nur, wenn die KI für die
  jeweilige Frage eingeschaltet ist (#215).

### Teilnahme

- Wortwolken- und Freitextantworten mit unsichtbaren Steuerzeichen führen
  nicht mehr zu einem Fehler; zusammengesetzte Emoji bleiben erhalten
  (#215).
- Links und QR-Codes der Lernkontrolle funktionieren in der
  Standardinstallation (#212).

### Ergebnisse und Export

- Im CSV-Export stehen Matrix-Koordinaten als echte Zahlen, und
  Kategorienamen der Matrix fallen bei fehlender Übersetzung auf die
  Hauptsprache zurück (#212, #215).

### Sicherheit

- **Für den Betrieb relevant:** Der OIDC-Abgleich per Benutzername ist
  standardmäßig aus und übernimmt nie lokale oder LTI-Konten; eine
  Namenskollision führt zu einer sauberen Ablehnung statt zu einem
  Serverfehler. Setzen Sie bei Bedarf `OIDC_MATCH_BY_USERNAME_FALLBACK=1`
  (#212, #213).
- **Für den Betrieb relevant:** Ohne eigenen `DJANGO_SECRET_KEY` startet
  eine Produktionsinstallation nicht mehr (#212).
- CSV-Export: Alle Textzellen sind gegen Formel-Injektion in
  Tabellenkalkulationen geschützt, auch Frage- und Antworttexte aus
  importierten oder geteilten Sets (#212).
- LTI: „Nutzende per E-Mail verknüpfen“ ist für neu angelegte Plattformen
  standardmäßig aus (#212).
- Abhängigkeiten mit bekannten Sicherheitslücken aktualisiert, u. a.
  Django 5.2 LTS, Pillow 12, pypdf 6 und react-router 7 (#214, #220).

### Deployment und Betrieb

- Die Caddyfile wird vollständig über Variablen in der `.env` konfiguriert;
  ein `git pull` bleibt nicht mehr an lokalen Änderungen hängen (#223).
- Installationsanleitung: neuer Pflichtschritt „Secret Key erzeugen“ und
  neues Kapitel „Bestehende Installation aktualisieren“ (#223).
- Die Installationsanleitung nennt die Pfade, die ein eigener
  Reverse-Proxy an Django weitergeben muss (#212).
- Das Image startet standardmäßig uvicorn; Caddy leitet `/c/*` an Django
  weiter (#212).
- Fragenset-Importe bis 10 MiB werden angenommen (#214).
- Laufzeit auf Node 24 LTS und Django 5.2 LTS angehoben; ungenutzte
  Abhängigkeiten entfernt (#214).
- Release-Images tragen die Versionsnummer aus dem Git-Tag und werden
  sowohl als `1.0.0` als auch als `v1.0.0` (und `latest`) veröffentlicht;
  für `ABSTIMMBAR_VERSION` eignet sich damit der Name des Git-Tags (#224).

### Barrierefreiheit

- Die Schaltflächen „Wieder einblenden“ bzw. „Wieder anzeigen“ in Mindmap,
  Wortwolke und Matrix haben Namen, die mit dem sichtbaren Text
  übereinstimmen (#218).
- Die Lasche „Hier einhängen“ der Mindmap hat einen zugänglichen Namen
  (#218).
- Die Füllpille am Beamer hat Screenreader-Beschriftungen je Zahl und
  verzichtet bei reduzierter Bewegung auf Animationen (#219).
- Die Rangliste der Mindmap wird als nummerierte Liste ausgegeben; Kontraste
  in Rangliste und Hinweisbannern verbessert (#215).
- Deaktivierte Bewertungsknöpfe der Matrix auf der Teilnahmeseite nennen
  den Grund, wie bei der Mindmap (#215).
- Nach einer Moderationsaktion springt der Fokus nicht mehr auf deaktivierte
  Knöpfe (#215).
- Selbst verfasste Tabellen, etwa in der Datenschutzerklärung, scrollen auf
  dem Smartphone in einem eigenen, per Tastatur erreichbaren Rahmen (#222).

### Entfernt

- API-Endpunkt `POST question-sets/<id>/reorder-sections/`; verwenden Sie
  `reorder-outline` (#216).
- Parameter `reset` beim Start einer Durchführung (`start-run`): Er wird
  ignoriert, maßgeblich ist allein `existing`. Ältere Skripte mit
  `reset: true` setzen eine Durchführung damit fort, statt sie zu löschen
  (#216).
- Interne Aufräumarbeiten: ungenutzter Code, verwaiste Übersetzungen und
  Datenbankfelder sowie die Abhängigkeit gunicorn (#214, #216).

## Vor 1.0

Abstimmbar entstand ab Juli 2026 bei virtUOS (Universität Osnabrück) als
Nachfolger des Stud.IP-Plugins Cliqr. Bis zur Version 1.0 wurde in diesen
Etappen entwickelt:

- **Fundament (M0):** Docker-Compose-Setup, Anmeldung per OpenID Connect mit
  Back-Channel-Logout, Oberfläche in React mit eigenem Erscheinungsbild.
- **Verwalten (M1):** Räume, Fragensets und Fragen mit WYSIWYG-Editor und
  Bildern; Einzel- und Mehrfachauswahl, Ja/Nein, Wortwolke; einstellbar,
  wann richtige Antworten gezeigt werden.
- **Durchführen (M2):** Live-Abstimmung mit Präsentationsmodus, QR-Code und
  Kurz-URL, anonyme Teilnahmeseite ohne Konto, Live-Ergebnisse; im Lasttest
  mit 1000 gleichzeitigen Teilnehmenden geprüft.
- **Auswerten (M3):** Ergebnisansicht, CSV-Export, Duplizieren und Kopieren
  von Fragensets, JSON-Export/-Import, Volltextsuche.
- **LTI 1.3 (M4):** Einbindung in Lernplattformen mit Kursraum-Verknüpfung
  und Deep Linking.
- **Weiterer Ausbau:** Likert-Skalen, Freitext, Sortierung, Prioritäten,
  Mindmap und Vier-Felder-Matrix mit Bewertungsphase; Countdown-Timer,
  Abschnitte, Bilder als Antwortoptionen; Set-Arten Live-Umfrage,
  Quiz-Block und Lernkontrolle; Teilen von Räumen und Sets; Zweisprachigkeit
  DE/EN für Oberfläche und Inhalte; optionale KI-Funktionen (Fragen aus
  Dokumenten, Wortwolken-, Freitext- und Mindmap-Auswertung);
  Statistikseite mit Prometheus-Export; geführter Rundgang mit Beispielraum;
  Mobilansicht und Kontraste nach WCAG AA.

## [0.1.2] – 2026-10-16

- Umfangreicher Funktionsstand vor 1.0: Set-Arten mit Lernkontrolle,
  Mindmap und Vier-Felder-Matrix mit Bewertung, neue Präsentationsansicht,
  geführter Rundgang, Statistikseite, KI-Funktionen, Mobilansicht und
  WCAG-AA-Kontraste.
- Automatisierte Ende-zu-Ende-Tests mit Playwright.

## [0.1.1] – 2026-08-07

- Aktualisierte gemeinsame Oberflächenbibliothek (@basicbar/ui 0.3.0).

## [0.1.0] – 2026-08-07

- Erste veröffentlichte Version mit automatisch gebautem Release-Image.
- Gemeinsame basicbar-Pakete werden aus den GitHub-Repositories bezogen.

[Unreleased]: https://github.com/virtUOS/abstimmbar/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/virtUOS/abstimmbar/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/virtUOS/abstimmbar/compare/v0.1.2...v1.0.0
[0.1.2]: https://github.com/virtUOS/abstimmbar/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/virtUOS/abstimmbar/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/virtUOS/abstimmbar/releases/tag/v0.1.0
