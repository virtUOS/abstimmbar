# ADR-0003: Realtime-Transport — SSE über async Django-Views mit In-Memory-Hub

- Status: **akzeptiert**
- Datum: 2026-07-06

## Kontext

M2 braucht die Push-Richtung Server → Clients: Fragenstatus und Zähler an
Teilnehmende und Präsentationsansicht. ADR-0001 hat „SSE zuerst" als
Grundsatz gesetzt; hier die konkrete Ausgestaltung.

## Entscheidung

1. **Server-Sent Events** über einen async Django-View
   (`StreamingHttpResponse` mit async Generator). Stimmabgabe und
   Steuerung bleiben normale POSTs.
2. **Ein Stream pro Raum** (`/api/live/rooms/<code>/stream`), zwei Rollen:
   Teilnehmende (öffentlich) und Präsentation (`?role=presenter`,
   nur Raum-Besitzer). Jedes Event ist ein **vollständiger
   Zustands-Snapshot** — ein Reconnect ist damit trivial korrekt, es gibt
   keine verpassten Deltas.
3. **In-Memory-Hub** (asyncio) im Prozess: Registry Raum → Subscriber-Queues,
   Broadcast mit **Debounce (~300 ms)** für Stimmen-Zähler, damit 1000
   schnelle Stimmen nicht 1000 × N Events erzeugen. Teilnehmer-Zähler =
   offene SSE-Verbindungen mit Rolle „participant".
4. **ASGI-Server: uvicorn** (statt `manage.py runserver`) in Dev und
   Produktion — SSE-Verbindungen belegen so keinen Thread pro Teilnehmer.
   Sync-Views (ORM) laufen unverändert im Threadpool; nur der Stream-View
   ist async. Sync-Code stößt Broadcasts über
   `asyncio.run_coroutine_threadsafe` an.

## Konsequenzen

- **Ein Prozess = konsistenter Zustand.** Der Hub lebt im Prozessspeicher;
  der Betrieb läuft mit **einem** uvicorn-Prozess (asyncio skaliert
  Verbindungen, die Last pro Event ist klein — Lasttest in M2 belegt die
  Zielgröße ≥ 1000). Scale-out auf mehrere Worker/Hosts erfordert später
  einen externen Pub/Sub (Redis) hinter derselben Hub-Schnittstelle —
  die API-Grenze ist dafür geschnitten (ADR-0001: notfalls eigener
  Fanout-Dienst).
- Kein Redis, keine Channels-Infrastruktur in v1.
- Proxies müssen SSE durchlassen (kein Response-Buffering für
  `text/event-stream`; Keepalive-Kommentare alle ~25 s sind eingebaut).
- Snapshot-statt-Delta kostet etwas Payload, kauft aber Korrektheit bei
  Reconnects und macht die Teilnehmer-Seite trivial (ein Handler).
