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
   das PDF serverseitig und deterministisch; eingebaute Helvetica genügt
   (WinAnsi deckt Deutsch inkl. „“ – ab; Zeichen außerhalb werden durch „?“
   ersetzt, statt das Rendern abzubrechen).
2. **Generischer Rahmen in `backend/common/pdf.py`** (`PdfDocument`,
   `html_to_flowables`, `safe_text`): Überschriften, Absätze, Editor-HTML,
   Listen, Tabellen, Kästen und eine Fußzeile „Seite x von y“ (zweiphasiger
   Canvas). Das Modul importiert nur Django, Stdlib und reportlab, damit es
   später unverändert in die basicbar-Pakete wandern kann.
3. **Inhalt gehört in die jeweilige App** (`committees/protocol_pdf.py`), nicht
   in den Rahmen.
4. Die **Druckansicht im Browser bleibt** als Alternative erhalten.

## Konsequenzen

- Eine neue Python-Dependency; Image-Rebuild nötig.
- Layout ist schlicht (keine Webfonts, kein CSS); dafür keine
  Browser-Abhängigkeit im Backend.
