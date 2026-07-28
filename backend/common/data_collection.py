# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Registry of personal data the system collects — the single source of
truth for the auto-generated section of the Datenschutz (privacy) page.

Whenever a feature starts collecting a new category of personal data, add an
entry here; the privacy page's data table updates automatically (it is
rendered from this list via the public ``/api/data-collection/`` endpoint).
The prose around the table stays admin-editable on the Datenschutz page.

Text is German on purpose — it feeds a legal page for a German university.
"""

# Each item: what is stored, why, the GDPR legal basis, and how long.
COLLECTED = [
    {
        "category": "Konto (Lehrende/Admins)",
        "data": "Name, E-Mail-Adresse, Nutzerkennung und OIDC-Kennung (Subject) "
                "aus dem Hochschul-Login (Single Sign-On).",
        "purpose": "Anmeldung, Zuordnung erstellter Räume und Fragensets, "
                   "gemeinsames Bearbeiten.",
        "legal_basis": "Art. 6 Abs. 1 lit. e DSGVO (Wahrnehmung einer Aufgabe "
                       "im öffentlichen Interesse – Lehre).",
        "retention": "Bis zur Löschung des Kontos bzw. Abmeldung aus dem Dienst.",
    },
    {
        "category": "Erstellte Inhalte",
        "data": "Räume, Fragensets, Fragen, Abschnitte und deren Metadaten "
                "(u. a. wer sie angelegt und zuletzt bearbeitet hat).",
        "purpose": "Bereitstellung der Kernfunktion (Erstellen und Durchführen "
                   "von Abstimmungen).",
        "legal_basis": "Art. 6 Abs. 1 lit. e DSGVO.",
        "retention": "Bis zur Löschung durch die erstellende Person.",
    },
    {
        "category": "LTI-Verknüpfung",
        "data": "Beim Start aus einem Lernmanagementsystem (LTI 1.3) die "
                "übermittelte E-Mail-Adresse zum Abgleich mit dem Konto.",
        "purpose": "Zuordnung des LTI-Starts zum vorhandenen Konto.",
        "legal_basis": "Art. 6 Abs. 1 lit. e DSGVO.",
        "retention": "Bis zur Löschung des Kontos.",
    },
    {
        "category": "KI-Auswertung (optional, nur bei aktivierter KI)",
        "data": "Sofern die optionalen KI-Funktionen aktiviert und von "
                "Lehrenden ausgelöst werden, werden bereits anonymisierte, "
                "aggregierte Abstimmungsergebnisse – einschließlich freier "
                "Text- und Wortwolken-Eingaben der Teilnehmenden sowie der "
                "Fragentexte – an den konfigurierten KI-Dienst (Sprachmodell) "
                "übermittelt. Beim Erzeugen von Fragen aus Dokumenten wird "
                "zusätzlich der Textinhalt der von Lehrenden hochgeladenen "
                "bzw. eingefügten Materialien übermittelt.",
        "purpose": "Optionale Aufbereitung durch Lehrende: Vorschläge im "
                   "Frage-Editor, Optimieren von Wortwolken, Kurzberichte zu "
                   "Durchführungen und Fragen aus Dokumenten generieren.",
        "legal_basis": "Art. 6 Abs. 1 lit. e DSGVO.",
        "retention": "In Abstimmbar werden dabei keine zusätzlichen Daten "
                     "gespeichert; die Übermittlung erfolgt nur auf manuelle "
                     "Auslösung. Verarbeitung beim KI-Dienst nach dessen "
                     "Vorgaben.",
    },
    {
        "category": "Sitzung",
        "data": "Ein technisch notwendiges Sitzungs-Cookie nach der Anmeldung.",
        "purpose": "Aufrechterhaltung der angemeldeten Sitzung.",
        "legal_basis": "Art. 6 Abs. 1 lit. e DSGVO; § 25 Abs. 2 TTDSG "
                       "(unbedingt erforderlich).",
        "retention": "Dauer der Sitzung.",
    },
    {
        "category": "Teilnahme-Kennung (anonym)",
        "data": "Eine zufällige, raumbezogene Kennung im lokalen Speicher des "
                "Geräts — ohne Personenbezug.",
        "purpose": "Verhindern von Mehrfachabstimmungen; Wiederaufnahme nach "
                   "Neuladen.",
        "legal_basis": "Art. 6 Abs. 1 lit. e DSGVO; § 25 Abs. 2 TTDSG.",
        "retention": "Verbleibt lokal auf dem Gerät; serverseitig an den "
                     "Durchlauf gebunden und mit dessen Löschung entfernt.",
    },
]

# Explicit reassurances (anonymity by design, concept §9).
NOT_COLLECTED = [
    (
        "Die Teilnahme an Abstimmungen ist anonym: kein Konto, kein Name, keine "
        "Anmeldung erforderlich."
    ),
    "Bei abgegebenen Stimmen werden keine IP-Adressen gespeichert.",
    "Es werden keine Tracking- oder Analyse-Cookies gesetzt.",
    "Es findet keine Weitergabe personenbezogener Daten an Dritte statt.",
]
