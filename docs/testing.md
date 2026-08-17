# Frontend-Tests (Playwright)

Die Management-UI wird per [Playwright](https://playwright.dev) End-to-End
getestet: ein echter Browser klickt sich durch die laufende App (Login,
Anlegen von Räumen/Fragensets, …). Die Tests liegen in
`frontend/e2e/*.spec.ts`, Konfiguration in `frontend/playwright.config.ts`.

## Voraussetzungen

Die Tests brauchen den laufenden Stack (Backend, Frontend-Dev-Server,
Keycloak, DB) unter den in der Haupt-`README`/`CLAUDE.md` beschriebenen
Ports (Frontend: `localhost:5174`, Keycloak: `localhost:8081`).

```bash
docker compose -f docker-compose.yml up -d            # db + keycloak + backend + frontend
docker compose exec backend python manage.py migrate  # migrate DB, only needed on first run
```

## Tests ausführen

```bash
cd frontend
npm install                       # einmalig, falls noch nicht geschehen
npx playwright install firefox    # einmalig: Browser-Binary laden
npm run e2e
```

Nützliche Varianten:

```bash
npx playwright test --headed      # Browser sichtbar mitlaufen lassen
npx playwright test --ui          # interaktiver Test-Runner (Debugging)
npx playwright show-report        # HTML-Report des letzten Laufs öffnen
```

Die Tests loggen sich über Keycloak mit dem Demo-Nutzer `demo`/`demo` ein
(siehe `CLAUDE.md`). Jeder Lauf legt neue Räume/Fragensets mit einem
Zeitstempel im Namen an, um Namenskollisionen zwischen Läufen zu vermeiden.

## Aufräumen nach Tests

Angelegte Räume (inkl. der darin enthaltenen Fragensets, per Cascade)
werden **nach jedem einzelnen Test** wieder gelöscht — nicht erst am Ende
des gesamten Laufs. Grund: bricht ein Test mittendrin ab (Assertion
schlägt fehl, Timeout, Absturz), würde ein einmaliges Aufräumen am Ende
nie erreicht und Testdaten blieben für alle folgenden Tests im Lauf
sichtbar (z. B. in „My rooms"). Pro-Test-Cleanup hält die Tests
unabhängig von Reihenfolge und Erfolg der anderen.

Umgesetzt über eine Playwright-Fixture (`frontend/e2e/fixtures.ts`):
`trackRoom(roomId)` merkt sich die ID, die Fixture löscht sie nach dem
Test per `DELETE /api/rooms/<id>/` (direkt gegen das Backend, nicht über
die UI — schneller und unabhängig vom UI-Zustand). Schlägt das Löschen
fehl (kein 2xx), wirft die Fixture einen Fehler, statt das stillschweigend
zu ignorieren — sonst würden verwaiste Testdaten unbemerkt bleiben.

```ts
import { test, expect } from './fixtures'; // statt '@playwright/test'

test('…', async ({ page, trackRoom }) => {
  // … Raum über die UI anlegen …
  const roomId = page.url().match(/\/rooms\/(\d+)/)?.[1];
  if (roomId) trackRoom(roomId);
  // … Rest des Tests …
});
```

## Neue Tests schreiben

Neue Spezifikationen kommen als `frontend/e2e/<name>.spec.ts` hinzu, eine
Datei pro sinnvoll abgeschlossenem Ablauf (z. B. ein Flow, keine einzelne
Aktion).

Grundgerüst:

```ts
import { test, expect } from './fixtures';

test('beschreibt, was der Test prüft', async ({ page }) => {
  await page.goto('/');
  // …Schritte…
  await expect(page.getByRole('heading', { name: 'Erwarteter Titel' })).toBeVisible();
});
```

Der Import aus `./fixtures` statt direkt aus `@playwright/test` ist wichtig,
sobald der Test einen Raum anlegt — nur so ist `trackRoom` in den
Testparametern verfügbar (siehe „Aufräumen nach Tests" oben). Für Tests
ohne Raumanlage funktioniert der Import genauso, `trackRoom` bleibt dann
einfach ungenutzt.

Hinweise:

- **Selektoren**: bevorzugt `page.getByRole(...)`, `getByLabel(...)`,
  `getByText(...)` — an sichtbaren Rollen/Labels orientiert, nicht an
  CSS-Klassen. Das hält Tests stabil gegenüber Styling-Änderungen und
  spiegelt, was Screenreader-Nutzer:innen sehen.
- **Kein manuelles Warten**: Playwright wartet automatisch, bis ein
  Element interagierbar ist bzw. eine `expect(...)`-Assertion erfüllt
  ist (mit Timeout und Retry). `page.waitForTimeout(...)` ist praktisch
  nie nötig.
- **Neue Selektoren finden**: `npx playwright codegen http://localhost:5174`
  öffnet einen Browser, zeichnet Klicks/Eingaben auf und generiert
  passenden Code dafür — guter Ausgangspunkt, den man danach aufräumt.
- **Isolation**: jeder Test bekommt einen frischen Browser-Context (keine
  gemeinsamen Cookies/Storage). Tests sollten nicht von der Ausführung
  anderer Tests abhängen — Namen/IDs entsprechend eindeutig wählen (siehe
  Zeitstempel-Muster oben).
- **Mehrsprachigkeit**: Sichtbare Texte sind über i18next lokalisiert
  (siehe `CLAUDE.md`, Abschnitt „Language convention"). Die Tests laufen
  gegen die Standardsprache der Anwendung — bei sprachabhängigen
  Selektoren (`getByText`, `getByRole(..., { name: "…" })`) im Zweifel
  `getByRole` mit stabilen ARIA-Rollen statt exaktem Text bevorzugen, oder
  auf `data-testid` ausweichen, falls ein Label mehrsprachig variiert.
