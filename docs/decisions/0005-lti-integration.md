# ADR-0005: LTI-1.3-Integration — pylti1p3, Kontext-Mapping, Nutzer-Modell

- Status: **akzeptiert**
- Datum: 2026-07-07

## Kontext

Konzept §8.1: Einbindung in LMS ausschließlich über LTI 1.3 / LTI
Advantage, kein 1.1-Fallback. Zu entscheiden: Bibliothek, Schlüssel- und
Registrierungs-Handling, das Mapping LMS-Kurs ↔ Raum und wie Lehrende und
Lernende aus einem Launch heraus behandelt werden.

## Entscheidung

1. **pylti1p3** (Paket `PyLTI1p3`, Django-Adapter) übernimmt den
   OIDC-Handshake, die id_token-Validierung, Nonce/State-Handling und die
   Deep-Linking-Antwort. Begründung wie ADR-0001: sicherheitskritischen
   JWT/OIDC-Code nicht selbst schreiben.
2. **Ein Tool-Schlüsselpaar** (RSA 2048, `LtiToolKey`, auto-generiert,
   in der DB) für alle Plattformen; veröffentlicht unter `/lti/jwks/`.
3. **Registrierung pro Plattform** (`LtiPlatform`: issuer, client_id,
   Auth-/Token-/JWKS-URLs oder Inline-Key-Set, deployment_ids) über den
   Django-Admin — das ist die „Admin-UI" der Roadmap für v1; Dynamic
   Registration bleibt v2.
4. **Kurskontext ↔ Raum** (`LtiContextLink`, unique pro Plattform+Kontext):
   beim ersten Instructor-Launch wird der Raum automatisch angelegt
   (Titel = Kurstitel) und die Lehrperson als Owner ergänzt. Weitere
   Lehrende desselben Kurses werden bei ihrem Launch ebenfalls Owner.
5. **Lehrende** werden just-in-time als `accounts.User` angelegt
   (Subject `lti:<plattform-pk>:<sub>`), analog zur OIDC-Provisionierung.
   **Lernende bekommen nie einen Account**: ein Learner-Launch leitet auf
   die anonyme Teilnehmer-Seite `/p/<code>/` um — Anonymität by design
   bleibt auch im LTI-Pfad erhalten.
6. **Deep Linking**: Auswahlseite (Django-Template) listet die Fragensets
   des Kurs-Raums bzw. legt ein neues an; der Rückgabe-Link trägt
   `custom.set`, ein Instructor-Launch damit landet direkt im Set.
7. **NRPS/AGS**: nicht in M4 (Roadmap: v2/Ausblick, braucht nicht-anonyme
   Durchführungen). Das Nutzer-/Vote-Modell hält den Weg offen.

## Konsequenzen

- Verifikation ohne LMS: die Test-Suite simuliert die Plattform (eigenes
  Schlüsselpaar, signierte id_tokens, kompletter Login→Launch-Handshake)
  inkl. Negativfällen (fremder Schlüssel, fremde deployment_id).
- iframe-Einbettung erfordert `SameSite=None`-Session-Cookies (nur über
  HTTPS); Default bleibt `Lax` — Empfehlung: Tool im LMS in neuem Fenster
  öffnen lassen (docs/lti.md).
- Ein Raum kann gleichzeitig OIDC- und LTI-Lehrende als Owner haben; das
  Rechtemodell bleibt unverändert (Owner-Prüfung überall identisch).
