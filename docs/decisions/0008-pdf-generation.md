# ADR-0008: PDF-Erzeugung mit reportlab

- Status: **akzeptiert**
- Datum: 2026-11-05

## Kontext

Das Sitzungsprotokoll des Gremien-Raums soll als PDF heruntergeladen werden
können (Archiv, Weitergabe, Unterschrift). Die Druckansicht im Browser bleibt
bestehen. ADR-0001 verlangt für jede neue Dependency eine Begründung.

## Entscheidung

1. **reportlab** (`reportlab==4.4.4`, wie in Kalkulierbar, dort ADR-0031):
   reine Python-Bibliothek ohne Systempakete oder Headless-Browser, erzeugt
   das PDF serverseitig und deterministisch.
   **Schrift: gebündelte Plus Jakarta Sans** (SIL Open Font License 1.1;
   TTFs und `OFL.txt` in `backend/common/fonts/`, im Image enthalten). Die
   eingebaute Helvetica (WinAnsi) scheiterte an Namen wie „Şahin“, „Łukasz“,
   „Dvořák“. Abgedeckt ist lateinische Schrift inkl. Erweiterungen sowie
   „ „ “ – › • → €“; **nicht** abgedeckt sind Griechisch, Kyrillisch, CJK und
   Emoji – solche Zeichen werden durch „?“ ersetzt (`safe_text` prüft gegen die
   Zeichentabelle der Schrift), statt das Rendern abzubrechen.
2. **Generischer Rahmen im Paket `basicbar-pdf`** (`PdfDocument`,
   `html_to_flowables`, `safe_text`): Überschriften, Absätze, Editor-HTML,
   Listen, Tabellen, Kästen und eine Fußzeile „Seite x von y“ (zweiphasiger
   Canvas). Zuerst entstand er als `backend/common/pdf.py`; seit November 2026
   liegt er samt Schrift in basicbar und wird auch von kalkulierbar genutzt.
   Seitenangabe und Bild-Platzhalter übergibt Abstimmbar als übersetzte
   Parameter.
3. **Inhalt gehört in die jeweilige App** (`committees/protocol_pdf.py`), nicht
   in den Rahmen.
4. Die **Druckansicht im Browser bleibt** als Alternative erhalten.

## Konsequenzen

- Eine neue Python-Dependency; Image-Rebuild nötig.
- Layout ist schlicht (keine Webfonts, kein CSS); dafür keine
  Browser-Abhängigkeit im Backend.
