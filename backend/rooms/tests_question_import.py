# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
import io
import json
import zipfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from PIL import Image

from rooms.question_import import core, detect, gift, h5p, ilias, licenses, safezip, simple
from rooms.question_import.core import (
    IMPORT_IMAGE_PREFIX,
    ImportFailed,
    ImportResult,
    finalize,
    true_false_labels,
)
from rooms.sanitize import clean_html, clean_media_url

ALL = ("single_choice", "multiple_choice", "open_text", "ordering")


def opts(draft):
    return [o["text"] for o in draft["options"]]


def correct(draft):
    return [o["text"] for o in draft["options"] if o["is_correct"]]


class SimpleFormatTests(SimpleTestCase):
    def test_single_choice(self):
        r = simple.parse(
            "F: Welche Stadt ist die Hauptstadt von Niedersachsen?\n"
            "* Hannover\n- Osnabrück\n- Braunschweig\n"
        )
        (d,) = r.drafts
        self.assertEqual(d["kind"], "single_choice")
        self.assertEqual(opts(d), ["Hannover", "Osnabrück", "Braunschweig"])
        self.assertEqual(correct(d), ["Hannover"])
        self.assertEqual(
            d["text"], "<p>Welche Stadt ist die Hauptstadt von Niedersachsen?</p>"
        )
        self.assertEqual(r.skipped, {})

    def test_multiple_tags(self):
        for tag in ("[mehrfach]", "[multiple]"):
            r = simple.parse(f"F: Gerade? {tag}\n* 2\n- 3\n* 4\n")
            (d,) = r.drafts
            self.assertEqual(d["kind"], "multiple_choice")
            self.assertEqual(d["text"], "<p>Gerade?</p>")
        r = simple.parse("F: Was? [mehrfach]\n- a\n- b\n")
        self.assertEqual(r.drafts[0]["kind"], "multiple_choice")
        self.assertEqual(correct(r.drafts[0]), [])

    def test_several_correct_is_multiple(self):
        r = simple.parse("F: x\n* a\n* b\n- c\n")
        self.assertEqual(r.drafts[0]["kind"], "multiple_choice")

    def test_poll_without_correct(self):
        r = simple.parse("F: Umfrage\n- a\n- b\n- c\n")
        (d,) = r.drafts
        self.assertEqual(d["kind"], "single_choice")
        self.assertEqual(correct(d), [])

    def test_true_false_wording_kept(self):
        for a, b in (("Wahr", "Falsch"), ("Richtig", "Falsch"), ("True", "False")):
            r = simple.parse(f"F: Aussage\n- {a}\n* {b}\n")
            (d,) = r.drafts
            self.assertEqual(d["kind"], "single_choice")
            self.assertTrue(d["binary_choice"])
            self.assertEqual(opts(d), [a, b])

    def test_ordering(self):
        r = simple.parse("F: Reihenfolge\n1. Planen\n2. Umsetzen\n3. Prüfen\n")
        (d,) = r.drafts
        self.assertEqual(d["kind"], "ordering")
        self.assertEqual(opts(d), ["Planen", "Umsetzen", "Prüfen"])

    def test_open_text(self):
        for prefix in ("L", "A"):
            r = simple.parse(f"F: Was nehmen Sie mit?\n{prefix}: Eine Lösung\n")
            (d,) = r.drafts
            self.assertEqual(d["kind"], "open_text")
            self.assertEqual(d["model_solution"], "Eine Lösung")
        r = simple.parse("F: Was nehmen Sie mit?\n")
        self.assertEqual(r.drafts[0]["kind"], "open_text")
        self.assertFalse(r.drafts[0].get("model_solution"))

    def test_prefix_variants_and_multiline(self):
        r = simple.parse("q: Zeile eins\nZeile zwei\n- a\n- b\n\nf: Zwei\n- x\n- y\n")
        self.assertEqual(len(r.drafts), 2)
        self.assertEqual(r.drafts[0]["text"], "<p>Zeile eins<br>Zeile zwei</p>")

    def test_no_blank_lines_and_comments(self):
        r = simple.parse(
            "# Kommentar\nF: Eins\n- a\n* b\n// noch einer\nF: Zwei\n* c\n- d\n"
        )
        self.assertEqual(len(r.drafts), 2)
        self.assertEqual(r.skipped, {})

    def test_invalid_reports_line(self):
        r = simple.parse("F: ok\n- a\n- b\n\nF: nur eine\n- a\n")
        self.assertEqual(len(r.drafts), 1)
        self.assertEqual(r.skipped, {("invalid", "Zeile 5"): 1})
        r = simple.parse("F: gemischt\n* a\n1. b\n")
        self.assertEqual(r.skipped, {("invalid", "Zeile 1"): 1})
        r = simple.parse("\nF:\n- a\n- b\n")
        self.assertEqual(r.drafts, [])
        self.assertEqual(r.skipped, {("invalid", "Zeile 2"): 1})

    def test_html_is_escaped(self):
        r = simple.parse("F: Was ist <b>fett</b>?\n- <i>a</i>\n- b\n")
        d = r.drafts[0]
        self.assertIn("&lt;b&gt;", d["text"])
        self.assertNotIn("<b>", d["text"])
        self.assertEqual(opts(d)[0], "<i>a</i>")

    def test_windows_line_endings_and_nbsp(self):
        r = simple.parse("﻿F: Frage\r\n* Ja\r\n- Nein\r\n")
        (d,) = r.drafts
        self.assertEqual(opts(d), ["Ja", "Nein"])
        self.assertEqual(d["text"], "<p>Frage</p>")

    def test_bullet_dash_reported_as_invalid(self):
        for marker in ("•", "–"):
            r = simple.parse(f"F: Frage\n{marker} a\n{marker} b\n")
            self.assertEqual(r.drafts, [])
            self.assertEqual(r.skipped, {("invalid", "Zeile 1"): 1})

    def test_website_example_files_parse(self):
        site = Path(settings.BASE_DIR).parent / "website"
        for rel in ("anleitung/beispiel-fragen.txt", "en/guide/example-questions.txt"):
            r = simple.parse((site / rel).read_text(encoding="utf-8"))
            self.assertEqual(r.skipped, {}, rel)
            self.assertEqual(
                [d["kind"] for d in r.drafts],
                ["single_choice", "multiple_choice", "single_choice", "ordering", "open_text"],
                rel,
            )
            self.assertTrue(r.drafts[2].get("binary_choice"), rel)
            self.assertTrue(r.drafts[4].get("model_solution"), rel)


def draft(kind="single_choice", n=2, text="<p>x</p>", opt_text="a"):
    return {
        "kind": kind,
        "text": text,
        "options": [{"text": opt_text, "is_correct": i == 0} for i in range(n)],
    }


class FinalizeTests(SimpleTestCase):
    def run_finalize(self, drafts, allowed=ALL):
        return finalize(ImportResult(format="simple", drafts=drafts), allowed)

    def test_too_many_options(self):
        r = self.run_finalize([draft(n=21)])
        self.assertEqual(r.drafts, [])
        self.assertEqual(r.skipped, {("too_many_options", ""): 1})

    def test_option_too_long_not_truncated(self):
        r = self.run_finalize([draft(opt_text="x" * 501), draft(opt_text="y" * 500)])
        self.assertEqual(len(r.drafts), 1)
        self.assertEqual(len(r.drafts[0]["options"][0]["text"]), 500)
        self.assertEqual(r.skipped, {("option_too_long", ""): 1})

    def test_text_too_long(self):
        r = self.run_finalize([draft(text="x" * 10_001)])
        self.assertEqual(r.skipped, {("text_too_long", ""): 1})

    def test_not_allowed(self):
        r = self.run_finalize(
            [draft("ordering", 3)], allowed=("single_choice", "multiple_choice")
        )
        self.assertEqual(r.drafts, [])
        self.assertEqual(r.skipped, {("not_allowed_in_set", "ordering"): 1})

    def test_over_limit(self):
        r = self.run_finalize([draft() for _ in range(205)])
        self.assertEqual(len(r.drafts), 200)
        self.assertEqual(r.skipped, {("over_limit", ""): 5})
        self.assertEqual(
            r.skipped_list(), [{"reason": "over_limit", "detail": "", "count": 5}]
        )

    def test_true_false_labels(self):
        self.assertEqual(true_false_labels(), ("Wahr", "Falsch"))
        with override_settings(CONTENT_DEFAULT_LANGUAGE="en"):
            self.assertEqual(true_false_labels(), ("True", "False"))


class GiftFormatTests(SimpleTestCase):
    def test_single_choice(self):
        r = gift.parse("Wer liegt im Grant-Grab? {~Grant ~Jefferson =niemand}")
        (d,) = r.drafts
        self.assertEqual(d["kind"], "single_choice")
        self.assertEqual(opts(d), ["Grant", "Jefferson", "niemand"])
        self.assertEqual(correct(d), ["niemand"])
        self.assertEqual(d["text"], "<p>Wer liegt im Grant-Grab?</p>")
        self.assertEqual(r.format, "gift")
        self.assertEqual(r.skipped, {})

    def test_weighted_is_multiple(self):
        r = gift.parse("Welche? {~%50%A ~%50%B ~%-100%C}")
        (d,) = r.drafts
        self.assertEqual(d["kind"], "multiple_choice")
        self.assertEqual(correct(d), ["A", "B"])

    def test_true_false(self):
        wahr, falsch = true_false_labels()
        for src, right in (("T", wahr), ("TRUE", wahr), ("F", falsch), ("FALSE", falsch)):
            r = gift.parse(f"Aussage. {{{src}}}")
            (d,) = r.drafts
            self.assertEqual(d["kind"], "single_choice")
            self.assertTrue(d["binary_choice"])
            self.assertEqual(opts(d), [wahr, falsch])
            self.assertEqual(correct(d), [right])
        r = gift.parse("Aussage. {T#nein#doch}")
        self.assertEqual(correct(r.drafts[0]), [wahr])

    def test_short_answer_and_essay(self):
        r = gift.parse("Hauptstadt? {=Paris =paris}")
        (d,) = r.drafts
        self.assertEqual(d["kind"], "open_text")
        self.assertEqual(d["model_solution"], "Paris")
        self.assertEqual(d["options"], [])
        r = gift.parse("Erzählen Sie. {}")
        (d,) = r.drafts
        self.assertEqual(d["kind"], "open_text")
        self.assertFalse(d.get("model_solution"))

    def test_unsupported_types(self):
        r = gift.parse("Pi? {#3.14:0.01}")
        self.assertEqual(r.drafts, [])
        self.assertEqual(r.skipped, {("unsupported_type", "numerical"): 1})
        r = gift.parse("Zuordnen {=a -> 1 =b -> 2 =c -> 3}")
        self.assertEqual(r.skipped, {("unsupported_type", "matching"): 1})
        r = gift.parse("Das ist {=x ~y} eine Lücke.")
        self.assertEqual(r.skipped, {("unsupported_type", "cloze"): 1})
        self.assertEqual(r.drafts, [])

    def test_title_category_comment_feedback_ignored(self):
        r = gift.parse(
            "$CATEGORY: foo\n\n// Kommentar\n::Titel:: Frage? {~falsch#Leider nein =richtig#Ja}"
        )
        (d,) = r.drafts
        self.assertNotIn("Titel", d["text"])
        self.assertEqual(opts(d), ["falsch", "richtig"])
        self.assertEqual(r.skipped, {})

    def test_escapes(self):
        r = gift.parse("Was ist 2 \\= 2? {=wahr ~falsch}")
        self.assertIn("2 = 2", r.drafts[0]["text"])
        r = gift.parse("Wie \\{x\\}? {=a\\~b ~c}")
        (d,) = r.drafts
        self.assertIn("{x}", d["text"])
        self.assertEqual(opts(d), ["a~b", "c"])

    def test_formats(self):
        r = gift.parse("[html]<b>fett</b> <script>x()</script>Frage {=a ~b}")
        d = r.drafts[0]
        self.assertIn("<b>fett</b>", d["text"])
        self.assertNotIn("<script", d["text"])
        for tag in ("markdown", "plain"):
            r = gift.parse(f"[{tag}]a <b>fett</b> Frage {{=a ~b}}")
            self.assertIn("&lt;b&gt;", r.drafts[0]["text"])
            self.assertNotIn("<b>", r.drafts[0]["text"])

    def test_html_image_dropped(self):
        r = gift.parse('[html]Siehe <img src="x.png"> Bild {=a ~b}')
        (d,) = r.drafts
        self.assertNotIn("<img", d["text"])
        self.assertEqual(r.skipped, {("image_dropped", ""): 1})

    def test_multiline_and_blank_separation(self):
        r = gift.parse(
            "Zeile eins\nZeile zwei {\n=a\n~b\n}\n\nZweite {T}\n"
        )
        self.assertEqual(len(r.drafts), 2)
        self.assertEqual(r.drafts[0]["text"], "<p>Zeile eins<br>Zeile zwei</p>")
        self.assertEqual(opts(r.drafts[0]), ["a", "b"])

    def test_invalid_and_description(self):
        r = gift.parse("Einzige Option {=a}\n\nNur Text ohne Block")
        self.assertEqual(r.skipped, {("unsupported_type", "description"): 1})
        self.assertEqual(r.drafts[0]["kind"], "open_text")
        r = gift.parse("Ohne Marker {foo}")
        self.assertEqual(r.skipped, {("invalid", "Zeile 1"): 1})
        r = gift.parse("Leere Option {=a ~}")
        self.assertEqual(r.skipped, {("invalid", "Zeile 1"): 1})

    def test_general_feedback_tail(self):
        r = gift.parse("Essay {####Allgemeines Feedback}")
        self.assertEqual(r.skipped, {})
        self.assertEqual(r.drafts[0]["kind"], "open_text")
        r = gift.parse("Frage? {=a#ja ~b#nein ####Allgemein}")
        (d,) = r.drafts
        self.assertEqual(d["kind"], "single_choice")
        self.assertEqual(opts(d), ["a", "b"])
        self.assertEqual(correct(d), ["a"])
        r = gift.parse("Frage? {T####fb}")
        self.assertTrue(r.drafts[0]["binary_choice"])

    def test_newline_and_backslash_escapes(self):
        r = gift.parse("Zeile\\nzwei {=a ~b}")
        self.assertEqual(r.drafts[0]["text"], "<p>Zeile<br>zwei</p>")
        r = gift.parse("Pfad C:\\\\x {=a\\\\ ~b}")
        (d,) = r.drafts
        self.assertIn("C:\\x", d["text"])
        self.assertEqual(opts(d), ["a\\", "b"])
        r = gift.parse("Backslash \\\\{=a ~b}")
        self.assertEqual(r.drafts[0]["text"], "<p>Backslash \\</p>")
        r = gift.parse("[html]a\\nb {=x ~y}")
        self.assertIn("a\nb", r.drafts[0]["text"])

    def test_looks_like_gift(self):
        self.assertTrue(gift.looks_like_gift("Frage? {=a ~b}"))
        self.assertTrue(gift.looks_like_gift("::T:: Text"))
        self.assertFalse(gift.looks_like_gift("F: Frage\n* a\n- b\n"))
        self.assertFalse(gift.looks_like_gift("Einfach Text"))

    def test_moodle_export_with_categories_and_comments(self):
        text = (
            "// question: 0  name: Switch category to $course$/top/Test\n"
            "$CATEGORY: $course$/top/Test\n\n"
            "// question: 1  name: Q1\n"
            "::Q1::Welche Farbe? {=Rot ~Blau ~Gelb}\n\n"
            "// question: 2  name: Q2\n"
            "::Q2::Mehrere? {~%50%A ~%50%B ~%-100%C}\n\n"
            "// question: 3\n"
            "::Q3::Erde ist rund. {TRUE#Nein#Ja}\n\n"
            "$CATEGORY: $course$/top/Zweite\n\n"
            "// question: 4\n::Q4::Hauptstadt? {=Berlin =berlin}\n\n"
            "// question: 5\n::Q5::Essay {}\n\n"
            "// question: 6\n::Q6::[html]<p>Fett <b>x</b></p>{=a ~b}\n\n"
            "// question: 7\n::Q7::Falsch? {F}\n\n"
            "// question: 8\n::Q8::Gewicht {~%100%a ~%0%b ~%0%c}\n"
        )
        r = gift.parse(text)
        self.assertEqual(len(r.drafts), 8)
        self.assertEqual(r.skipped, {})


def make_zip(entries: dict[str, bytes | str], compression=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


class SafeZipTests(SimpleTestCase):
    def test_broken_bytes(self):
        with self.assertRaises(ImportFailed):
            safezip.open_zip(b"definitely not a zip")

    def test_declared_size_over_limit(self):
        # highly compressible zeros: 31 MB declared, tiny on the wire
        data = make_zip({"big.bin": b"\0" * (31 * 1024 * 1024)})
        self.assertLess(len(data), 1024 * 1024)
        with self.assertRaises(ImportFailed):
            safezip.open_zip(data)

    def test_too_many_entries(self):
        data = make_zip({f"f{i}.txt": "x" for i in range(501)})
        with self.assertRaises(ImportFailed):
            safezip.open_zip(data)

    def test_500_entries_ok(self):
        zf = safezip.open_zip(make_zip({f"f{i}.txt": "x" for i in range(500)}))
        self.assertEqual(len(safezip.names(zf)), 500)

    def test_unsafe_names_ignored_and_rejected(self):
        zf = safezip.open_zip(
            make_zip({"../evil": "x", "/abs": "x", "a/../../b": "x", "ok.txt": "fine"})
        )
        self.assertEqual(safezip.names(zf), ["ok.txt"])
        for bad in ("../evil", "/abs", "a/../../b"):
            with self.assertRaises(ImportFailed):
                safezip.read(zf, bad, 100)
        self.assertEqual(safezip.read(zf, "ok.txt", 100), b"fine")

    def test_read_streams_with_cap(self):
        zf = safezip.open_zip(make_zip({"a.txt": b"x" * 1000}))
        with self.assertRaises(ImportFailed):
            safezip.read(zf, "a.txt", 999)
        self.assertEqual(len(safezip.read(zf, "a.txt", 1000)), 1000)

    def test_read_missing(self):
        zf = safezip.open_zip(make_zip({"a.txt": "x"}))
        with self.assertRaises(ImportFailed):
            safezip.read(zf, "nope.txt", 10)


# Field names compared on 2026-11-19 against the public semantics.json of
# h5p/h5p-multi-choice, h5p/h5p-true-false, h5p/h5p-single-choice-set and
# otacke/h5p-essay (GitHub); QuestionSet/Column shapes follow the spec. No
# real export was available without a login. No third-party .h5p is committed.
def h5p_zip(main: str, content, extra: dict | None = None) -> zipfile.ZipFile:
    entries = {
        "h5p.json": json.dumps({"title": "T", "mainLibrary": main}),
        "content/content.json": json.dumps(content),
    }
    entries.update(extra or {})
    return safezip.open_zip(make_zip(entries))


def mc(question="<p>Q?</p>", answers=(("A", True), ("B", False)), **extra):
    return {
        "question": question,
        "answers": [
            {"text": f"<div>{t}</div>\n", "correct": c, "tipsAndFeedback": {}}
            for t, c in answers
        ],
        **extra,
    }


class H5PTests(SimpleTestCase):
    def test_is_h5p(self):
        self.assertTrue(h5p.is_h5p(h5p_zip("H5P.MultiChoice 1.16", mc())))
        self.assertFalse(h5p.is_h5p(safezip.open_zip(make_zip({"qti.xml": "<x/>"}))))

    def test_multichoice_single(self):
        r = h5p.parse(h5p_zip("H5P.MultiChoice 1.16", mc()))
        self.assertEqual(r.format, "h5p")
        [d] = r.drafts
        self.assertEqual(d["kind"], "single_choice")
        self.assertEqual(d["text"], "<p>Q?</p>")
        self.assertEqual(opts(d), ["A", "B"])
        self.assertEqual(correct(d), ["A"])
        self.assertEqual(r.skipped, {})

    def test_multichoice_multiple(self):
        r = h5p.parse(h5p_zip(
            "H5P.MultiChoice 1.16", mc(answers=(("A", True), ("B", True), ("C", False)))
        ))
        self.assertEqual(r.drafts[0]["kind"], "multiple_choice")
        self.assertEqual(correct(r.drafts[0]), ["A", "B"])

    def test_multichoice_without_correct_is_invalid(self):
        r = h5p.parse(h5p_zip("H5P.MultiChoice 1.16", mc(answers=(("A", False), ("B", False)))))
        self.assertEqual(r.drafts, [])
        self.assertEqual(r.skipped, {("invalid", "H5P.MultiChoice"): 1})

    @override_settings(CONTENT_DEFAULT_LANGUAGE="de")
    def test_truefalse(self):
        r = h5p.parse(h5p_zip("H5P.TrueFalse 1.8", {"question": "<p>Himmel blau?</p>", "correct": "true"}))
        [d] = r.drafts
        self.assertTrue(d["binary_choice"])
        self.assertEqual(opts(d), ["Wahr", "Falsch"])
        self.assertEqual(correct(d), ["Wahr"])

    @override_settings(CONTENT_DEFAULT_LANGUAGE="en")
    def test_truefalse_false_english(self):
        r = h5p.parse(h5p_zip("H5P.TrueFalse 1.8", {"question": "<p>Q</p>", "correct": "false"}))
        self.assertEqual(correct(r.drafts[0]), ["False"])

    def test_single_choice_set(self):
        content = {"choices": [
            {"question": "<p>Q1</p>", "answers": ["<p>Right</p>", "Wrong", "Wrong2"]},
            {"question": "<p>Q2</p>", "answers": ["R", "W"]},
        ]}
        r = h5p.parse(h5p_zip("H5P.SingleChoiceSet 1.11", content))
        self.assertEqual([d["kind"] for d in r.drafts], ["single_choice"] * 2)
        self.assertEqual(correct(r.drafts[0]), ["Right"])
        self.assertEqual(opts(r.drafts[1]), ["R", "W"])

    def test_essay_with_sample(self):
        content = {
            "taskDescription": "<p>Explain.</p>",
            "solution": {"introduction": "", "sample": "<p>Line one</p><p>Line &amp; two</p>"},
        }
        [d] = h5p.parse(h5p_zip("H5P.Essay 1.5", content)).drafts
        self.assertEqual(d["kind"], "open_text")
        self.assertEqual(d["model_solution"], "Line one\nLine & two")
        self.assertNotIn("<", d["model_solution"])
        self.assertNotIn("ai_evaluate", d)

    def test_essay_without_sample(self):
        [d] = h5p.parse(h5p_zip("H5P.Essay 1.5", {"taskDescription": "<p>Explain.</p>"})).drafts
        self.assertNotIn("model_solution", d)

    def test_question_set_skips_unsupported(self):
        content = {"questions": [
            {"library": "H5P.MultiChoice 1.16", "params": mc()},
            {"library": "H5P.Blanks 1.14", "params": {"questions": ["*x*"]}},
        ]}
        r = h5p.parse(h5p_zip("H5P.QuestionSet 1.20", content))
        self.assertEqual(len(r.drafts), 1)
        self.assertEqual(r.skipped, {("unsupported_type", "H5P.Blanks"): 1})

    def test_column_recursive(self):
        content = {"content": [
            {"content": {"library": "H5P.MultiChoice 1.16", "params": mc()}},
            {"content": {"library": "H5P.QuestionSet 1.20", "params": {"questions": [
                {"library": "H5P.TrueFalse 1.8", "params": {"question": "Q", "correct": "true"}},
            ]}}},
        ]}
        r = h5p.parse(h5p_zip("H5P.Column 1.18", content))
        self.assertEqual(len(r.drafts), 2)

    def test_unsupported_main_library(self):
        r = h5p.parse(h5p_zip("H5P.Blanks 1.14", {"questions": []}))
        self.assertEqual(r.drafts, [])
        self.assertEqual(r.skipped, {("unsupported_type", "H5P.Blanks"): 1})

    def test_media_image_dropped_question_kept(self):
        media = {"type": {"library": "H5P.Image 1.1", "params": {"file": {"path": "images/a.png"}}}}
        r = h5p.parse(h5p_zip("H5P.MultiChoice 1.16", mc(media=media)))
        self.assertEqual(len(r.drafts), 1)
        self.assertEqual(r.skipped, {("image_dropped", ""): 1})

    def test_inline_img_stripped(self):
        r = h5p.parse(h5p_zip("H5P.MultiChoice 1.16", mc(question='<p>Q <img src="a.png"> ?</p>')))
        self.assertNotIn("<img", r.drafts[0]["text"])
        self.assertEqual(r.skipped, {("image_dropped", ""): 1})

    def test_question_html_sanitized(self):
        r = h5p.parse(h5p_zip("H5P.MultiChoice 1.16", mc(question='<p>Q<script>x()</script></p>')))
        self.assertNotIn("script", r.drafts[0]["text"])

    def test_missing_content_json(self):
        zf = safezip.open_zip(make_zip({"h5p.json": json.dumps({"mainLibrary": "H5P.MultiChoice 1.16"})}))
        with self.assertRaises(ImportFailed):
            h5p.parse(zf)

    def test_invalid_json(self):
        zf = safezip.open_zip(make_zip({"h5p.json": "{", "content/content.json": "{}"}))
        with self.assertRaises(ImportFailed):
            h5p.parse(zf)

    def test_content_json_too_large(self):
        big = json.dumps({"x": "a" * (5 * 1024 * 1024 + 10)})
        zf = safezip.open_zip(make_zip({"h5p.json": "{}", "content/content.json": big}))
        with self.assertRaises(ImportFailed):
            h5p.parse(zf)

    def test_deeply_nested_json_fails_cleanly(self):
        deep = "[" * 200000 + "]" * 200000
        zf = safezip.open_zip(make_zip({"h5p.json": "{}", "content/content.json": deep}))
        with self.assertRaises(ImportFailed):
            h5p.parse(zf)

    def test_non_list_container_fields(self):
        for lib, key in (
            ("H5P.QuestionSet 1.20", "questions"),
            ("H5P.Column 1.18", "content"),
            ("H5P.SingleChoiceSet 1.11", "choices"),
        ):
            for bad in (5, True, "abc"):
                r = h5p.parse(h5p_zip(lib, {key: bad}))
                self.assertEqual(r.drafts, [])
                self.assertEqual(sum(r.skipped.values()), 1, (lib, bad))
                [(reason, _)] = r.skipped
                self.assertEqual(reason, "invalid")


# ILIAS QTI 1.2: element names, QUESTIONTYPE values and resprocessing patterns
# were compared on 2026-11-19 against the public ILIAS source on GitHub
# (ILIAS-eLearning/ILIAS, branch trunk): components/ILIAS/TestQuestionPool/
# classes/export/qti12/class.ass{SingleChoice,MultipleChoice,OrderingQuestion,
# TextQuestion,KprimChoice,Question}Export.php, the importers
# classes/import/qti12/class.ass{Ordering,MultipleChoice,Text}QuestionImport.php
# and classes/QTI/class.ilQTIItem.php (legacy "... QUESTION" type names vs.
# current "ass*" ids). Findings encoded in the fixtures: test exports wrap items
# in assessment/section; ordering labels carry nested <material> plus an
# "answerdepth" mattext and composite idents; the ordering varequal text is the
# label's position, its index attribute the solution rank; feedback conditions
# (response_allcorrect) have varequals but no setvar. No real export file was
# available; the fixtures in test_fixtures/import/ are self-authored (no
# third-party file committed).
FIXTURES = Path(__file__).parent / "test_fixtures" / "import"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def qti(*items: str, doctype: str = "") -> bytes:
    return (doctype + "<questestinterop>" + "".join(items) + "</questestinterop>").encode()


def qti_item(qtype="SINGLE CHOICE QUESTION", question="<mattext>Q?</mattext>", response="", resprocessing=""):
    return (
        '<item ident="il_0_qst_1" title="T"><itemmetadata><qtimetadata>'
        f"<qtimetadatafield><fieldlabel>QUESTIONTYPE</fieldlabel><fieldentry>{qtype}</fieldentry></qtimetadatafield>"
        f"</qtimetadata></itemmetadata><presentation><flow><material>{question}</material>{response}</flow></presentation>"
        f"<resprocessing>{resprocessing}</resprocessing></item>"
    )


def choice_response(ident="MCSR", labels=("A", "B")):
    return (
        f'<response_lid ident="{ident}"><render_choice>'
        + "".join(
            f'<response_label ident="{i}"><material><mattext>{t}</mattext></material></response_label>'
            for i, t in enumerate(labels)
        )
        + "</render_choice></response_lid>"
    )


def cond(ident, points, respident="MCSR", negate=False, index=None):
    attr = f' index="{index}"' if index is not None else ""
    ve = f'<varequal respident="{respident}"{attr}>{ident}</varequal>'
    if negate:
        ve = f"<not>{ve}</not>"
    sv = f'<setvar action="Add">{points}</setvar>' if points is not None else ""
    return f"<respcondition><conditionvar>{ve}</conditionvar>{sv}</respcondition>"


class IliasLegacyFixtureTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.result = ilias.parse_xml(fixture("ilias_legacy_qti.xml"))
        cls.drafts = cls.result.drafts

    def test_format_and_counts(self):
        self.assertEqual(self.result.format, "ilias")
        self.assertEqual(
            [d["kind"] for d in self.drafts],
            ["single_choice", "multiple_choice", "open_text", "ordering"],
        )

    def test_single_choice(self):
        d = self.drafts[0]
        self.assertEqual(d["text"], "<p>Was ist die Hauptstadt von <strong>Frankreich</strong>?</p>")
        self.assertEqual(opts(d), ["Berlin", "Paris", "Rom & Mailand"])
        self.assertEqual(correct(d), ["Paris"])

    def test_multiple_choice_ignores_not_and_feedback(self):
        d = self.drafts[1]
        self.assertEqual(d["text"], "<p>Welche Zahlen sind Primzahlen?</p>")
        self.assertEqual(opts(d), ["2", "4", "7", "9"])
        self.assertEqual(correct(d), ["2", "7"])

    def test_text_question(self):
        d = self.drafts[2]
        self.assertEqual(d["options"], [])
        self.assertIn("Erläutern Sie den Begriff.", d["text"])
        self.assertNotIn("script", d["text"])
        self.assertNotIn("model_solution", d)
        self.assertNotIn("ai_evaluate", d)

    def test_ordering_in_solution_order(self):
        d = self.drafts[3]
        self.assertEqual(opts(d), ["eins", "zwei", "drei"])
        self.assertEqual(correct(d), [])

    def test_skipped(self):
        self.assertEqual(self.result.skipped, {
            ("unsupported_type", "ORDERING QUESTION (image)"): 1,
            ("unsupported_type", "KPRIM CHOICE QUESTION"): 1,
            ("unsupported_type", "CLOZE QUESTION"): 1,
            ("unsupported_type", "MATCHING QUESTION"): 1,
        })


class IliasTrunkFixtureTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.result = ilias.parse_xml(fixture("ilias_trunk_test_qti.xml"))
        cls.drafts = cls.result.drafts

    def test_items_inside_assessment_section(self):
        self.assertEqual(
            [d["kind"] for d in self.drafts],
            ["single_choice", "ordering", "multiple_choice"],
        )
        self.assertEqual(self.result.skipped, {
            # The media object behind an uri needs the ZIP; the base64 option
            # image (Gold) is kept.
            ("image_dropped", ""): 1,
            ("unsupported_type", "assKprimChoice"): 1,
        })

    def test_media_object_image_removed(self):
        d = self.drafts[0]
        self.assertNotIn("<img", d["text"])
        self.assertNotIn("il_0_mob", d["text"])
        self.assertIn("Welches Tier sehen Sie?", d["text"])
        self.assertEqual(correct(d), ["Katze"])

    def test_nested_ordering_material_and_composite_idents(self):
        d = self.drafts[1]
        self.assertEqual(opts(d), ["Planung", "Umsetzung", "Auswertung"])

    def test_option_image_kept_text_kept(self):
        d = self.drafts[2]
        self.assertEqual(opts(d), ["Schwarz", "Blau", "Gold"])
        self.assertEqual(correct(d), ["Schwarz", "Gold"])
        self.assertEqual([o.get("image", "") for o in d["options"]], ["", "", IMPORT_IMAGE_PREFIX + "1"])
        self.assertEqual(self.result.images[IMPORT_IMAGE_PREFIX + "1"].data, b"\x89PNG\r\n\x1a\n")


class IliasTests(SimpleTestCase):
    def test_looks_like_qti(self):
        self.assertTrue(ilias.looks_like_qti(fixture("ilias_legacy_qti.xml")))
        self.assertTrue(ilias.looks_like_qti(b"<questestinterop/>"))
        self.assertFalse(ilias.looks_like_qti(b"<quiz/>"))
        self.assertFalse(ilias.looks_like_qti(b"not xml at all"))
        self.assertFalse(ilias.looks_like_qti(b""))

    def test_find_qti(self):
        zf = safezip.open_zip(make_zip({
            "1234__0__tst_56/1234__0__tst_56.xml": "<x/>",
            "1234__0__tst_56/1234__0__qti_56.xml": "<questestinterop/>",
            "1234__0__tst_56/objects/il_0_mob_1/a.png": b"\x89PNG",
        }))
        self.assertEqual(ilias.find_qti(zf), "1234__0__tst_56/1234__0__qti_56.xml")
        zf = safezip.open_zip(make_zip({"pool/export_qti.xml": "<questestinterop/>"}))
        self.assertEqual(ilias.find_qti(zf), "pool/export_qti.xml")
        zf = safezip.open_zip(make_zip({"h5p.json": "{}"}))
        self.assertIsNone(ilias.find_qti(zf))

    def test_parse_zip(self):
        data = make_zip({"1234__0__qpl_56/1234__0__qti_56.xml": fixture("ilias_legacy_qti.xml")})
        r = ilias.parse(safezip.open_zip(data))
        self.assertEqual(len(r.drafts), 4)
        with self.assertRaises(ImportFailed):
            ilias.parse(safezip.open_zip(make_zip({"a.txt": "x"})))

    def test_plain_question_text_escaped(self):
        r = ilias.parse_xml(qti(qti_item(
            question='<mattext texttype="text/plain">1 &lt; 2\nZeile 2</mattext>',
            response=choice_response(), resprocessing=cond(0, 1) + cond(1, 0),
        )))
        self.assertEqual(r.drafts[0]["text"], "<p>1 &lt; 2<br>Zeile 2</p>")

    def test_option_text_verbatim_not_truncated(self):
        long = "x" * 600
        r = ilias.parse_xml(qti(qti_item(response=choice_response(labels=(long, "B")),
                                         resprocessing=cond(0, 1))))
        self.assertEqual(r.drafts[0]["options"][0]["text"], long)

    def test_inline_img_with_foreign_src_removed(self):
        r = ilias.parse_xml(qti(qti_item(
            question='<mattext texttype="text/xhtml">&lt;p&gt;Q &lt;img src="https://evil.example/x.png"&gt;&lt;/p&gt;</mattext>',
            response=choice_response(), resprocessing=cond(0, 1),
        )))
        self.assertNotIn("<img", r.drafts[0]["text"])
        self.assertNotIn("evil", r.drafts[0]["text"])
        self.assertEqual(r.skipped, {("image_dropped", ""): 1})

    def test_obfuscated_img_removed(self):
        for markup in (
            '&lt;p&gt;Q &lt;im&lt;img&gt;g src="https://evil.example/x.png"&gt;&lt;/p&gt;',
            '&lt;p&gt;Q &lt;image src="https://evil.example/x.png"&gt;&lt;/p&gt;',
        ):
            r = ilias.parse_xml(qti(qti_item(
                question=f'<mattext texttype="text/xhtml">{markup}</mattext>',
                response=choice_response(), resprocessing=cond(0, 1),
            )))
            self.assertNotIn("<img", r.drafts[0]["text"], markup)
            self.assertNotIn("evil", r.drafts[0]["text"], markup)
            self.assertEqual(r.skipped, {("image_dropped", ""): 1}, markup)

    def test_image_dropped_only_when_question_kept(self):
        r = ilias.parse_xml(qti(qti_item(
            question='<mattext texttype="text/xhtml">&lt;p&gt;Q &lt;img src="a.png"&gt;&lt;/p&gt;</mattext>',
            response=choice_response(labels=("only",)), resprocessing=cond(0, 1),
        )))
        self.assertEqual(r.drafts, [])
        self.assertEqual(r.skipped, {("invalid", "SINGLE CHOICE QUESTION"): 1})

    def test_choice_with_image_only_option_skipped(self):
        response = (
            '<response_lid ident="MCSR"><render_choice>'
            '<response_label ident="0"><material><mattext>A</mattext></material></response_label>'
            '<response_label ident="1"><material><matimage label="b.png"/></material></response_label>'
            "</render_choice></response_lid>"
        )
        r = ilias.parse_xml(qti(qti_item(response=response, resprocessing=cond(0, 1))))
        self.assertEqual(r.drafts, [])
        self.assertEqual(r.skipped, {("unsupported_type", "SINGLE CHOICE QUESTION (image)"): 1})

    def test_negative_and_non_numeric_points_not_correct(self):
        r = ilias.parse_xml(qti(qti_item(
            qtype="MULTIPLE CHOICE QUESTION",
            response=choice_response("MCMR", ("A", "B", "C", "D")),
            resprocessing=cond(0, "abc", "MCMR") + cond(1, -2, "MCMR") + cond(2, "1.5", "MCMR")
            + cond(3, 1, "MCMR", negate=True) + cond(3, None, "MCMR"),
        )))
        self.assertEqual(correct(r.drafts[0]), ["C"])

    def test_ordering_resolved_by_position_and_index(self):
        r = ilias.parse_xml(qti(qti_item(
            qtype="assOrderingQuestion",
            response=choice_response("OQNT", ("c", "a", "b")),
            resprocessing=cond(0, 1, "OQNT", index=2) + cond(1, 1, "OQNT", index=0) + cond(2, 1, "OQNT", index=1),
        )))
        self.assertEqual(opts(r.drafts[0]), ["a", "b", "c"])
        self.assertEqual(r.drafts[0]["kind"], "ordering")

    def test_ordering_broken_solution_invalid(self):
        broken = (
            cond(0, 1, "OQT", index=0),  # incomplete
            cond(0, 1, "OQT", index=0) + cond(1, 1, "OQT", index=0),  # duplicate rank
            cond(0, 1, "OQT", index=0) + cond(5, 1, "OQT", index=1),  # out of range
            cond(0, 1, "OQT", index="x") + cond(1, 1, "OQT", index=1),  # non-numeric
            cond("", 1, "OQT", index=0) + cond(1, 1, "OQT", index=1),  # empty varequal
            cond("\u00b2", 1, "OQT", index=0) + cond(1, 1, "OQT", index=1),  # non-ASCII digit
            cond(0, 1, "OQT", index="\u00b2") + cond(1, 1, "OQT", index=1),
            cond("9" * 5000, 1, "OQT", index=0) + cond(1, 1, "OQT", index=1),  # int() length limit
            cond(0, 1, "OQT", index="9" * 5000) + cond(1, 1, "OQT", index=1),
        )
        for rp in broken:
            r = ilias.parse_xml(qti(qti_item(
                qtype="ORDERING QUESTION", response=choice_response("OQT", ("a", "b")), resprocessing=rp,
            )))
            self.assertEqual(r.drafts, [], rp)
            self.assertEqual(r.skipped, {("invalid", "ORDERING QUESTION"): 1}, rp)

    def test_unsupported_detail_bounded(self):
        r = ilias.parse_xml(qti(qti_item(qtype="X" * 500)))
        [(reason, detail)] = r.skipped
        self.assertEqual(reason, "unsupported_type")
        self.assertLessEqual(len(detail), 80)

    def test_missing_parts_reported_not_raised(self):
        items = (
            '<item ident="a"/>',
            (
                '<item ident="b"><itemmetadata><qtimetadata><qtimetadatafield><fieldlabel>QUESTIONTYPE</fieldlabel>'
                "<fieldentry>assSingleChoice</fieldentry></qtimetadatafield></qtimetadata></itemmetadata></item>"
            ),
            qti_item(response=""),
            qti_item(qtype="TEXT QUESTION", question=""),
            qti_item(qtype="assOrderingQuestion", response=""),
        )
        r = ilias.parse_xml(qti(*items))
        self.assertEqual(r.drafts, [])
        self.assertEqual(sum(r.skipped.values()), 5)

    def test_choice_without_correct_kept(self):
        r = ilias.parse_xml(qti(qti_item(response=choice_response(), resprocessing=cond(0, 0))))
        self.assertEqual(r.drafts[0]["kind"], "single_choice")
        self.assertEqual(correct(r.drafts[0]), [])


class SafeXmlTests(SimpleTestCase):
    def test_external_doctype_accepted(self):
        root = core.safe_xml(b'<?xml version="1.0"?><!DOCTYPE questestinterop SYSTEM "ims_qtiasiv1p2p1.dtd"><questestinterop/>')
        self.assertEqual(root.tag, "questestinterop")

    def test_xxe_rejected(self):
        data = (
            b'<?xml version="1.0"?><!DOCTYPE questestinterop [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
            + qti(qti_item(question="<mattext>&xxe;</mattext>", response=choice_response(), resprocessing=cond(0, 1)))
        )
        with self.assertRaises(ImportFailed):
            ilias.parse_xml(data)

    def test_internal_entity_rejected(self):
        data = b'<?xml version="1.0"?><!DOCTYPE questestinterop [<!ENTITY a "x">]><questestinterop>&a;</questestinterop>'
        with self.assertRaises(ImportFailed):
            core.safe_xml(data)

    def test_billion_laughs_rejected(self):
        ents = '<!ENTITY a "aaaaaaaaaa">' + "".join(
            f'<!ENTITY {chr(98 + i)} "{("&" + chr(97 + i) + ";") * 10}">' for i in range(9)
        )
        data = f'<?xml version="1.0"?><!DOCTYPE questestinterop [{ents}]><questestinterop>&j;</questestinterop>'
        with self.assertRaises(ImportFailed):
            ilias.parse_xml(data.encode())

    def test_malformed_inputs(self):
        for data in (b"", b"<questestinterop>", b"\xff\xfe garbage", b"<a>" * 300 + b"</a>" * 300,
                     b"<quiz/>", b"<r>&undefined;</r>"):
            with self.assertRaises(ImportFailed, msg=data[:20]):
                ilias.parse_xml(data)


class SharedImageCleaningTests(SimpleTestCase):
    """R6: one image-safe sanitizer in core, used by GIFT, H5P and ILIAS."""

    TRICKS = ('Q <im<img>g src="x.png"> Ende', 'Q <image src="x.png"> Ende')

    def test_core_clean_without_images(self):
        for markup in self.TRICKS:
            html, dropped = core.clean_without_images(f"<p>{markup}</p>")
            self.assertNotIn("<img", html, markup)
            self.assertNotIn("x.png", html, markup)
            self.assertTrue(dropped, markup)
        self.assertEqual(core.clean_without_images("<p>ohne</p>"), ("<p>ohne</p>", False))

    def test_gift_obfuscated_img_removed(self):
        for markup in self.TRICKS:
            r = gift.parse(f"[html]{markup} {{=a ~b}}")
            (d,) = r.drafts
            self.assertNotIn("<img", d["text"], markup)
            self.assertNotIn("x.png", d["text"], markup)
            self.assertEqual(r.skipped, {("image_dropped", ""): 1}, markup)

    def test_h5p_obfuscated_img_removed(self):
        for markup in self.TRICKS:
            r = h5p.parse(h5p_zip("H5P.MultiChoice 1.16", mc(question=f"<p>{markup}</p>")))
            (d,) = r.drafts
            self.assertNotIn("<img", d["text"], markup)
            self.assertNotIn("x.png", d["text"], markup)
            self.assertEqual(r.skipped, {("image_dropped", ""): 1}, markup)


class FinalizeSingleChoiceTests(SimpleTestCase):
    """R7: a non-binary single choice with several correct options becomes MC."""

    def test_several_correct_single_choice_becomes_multiple(self):
        d = draft(n=3)
        d["options"][1]["is_correct"] = True
        r = finalize(ImportResult(format="ilias", drafts=[d]), ALL)
        (out,) = r.drafts
        self.assertEqual(out["kind"], "multiple_choice")
        self.assertEqual(opts(out), ["a", "a", "a"])
        self.assertEqual(out["text"], "<p>x</p>")

    def test_one_correct_and_binary_unchanged(self):
        r = finalize(ImportResult(format="ilias", drafts=[draft(n=3)]), ALL)
        self.assertEqual(r.drafts[0]["kind"], "single_choice")
        b = draft(n=2)
        b["binary_choice"] = True
        b["options"][1]["is_correct"] = True
        r = finalize(ImportResult(format="gift", drafts=[b]), ALL)
        self.assertEqual(r.drafts[0]["kind"], "single_choice")

    def test_converted_kind_checked_against_set(self):
        d = draft(n=3)
        d["options"][1]["is_correct"] = True
        r = finalize(ImportResult(format="ilias", drafts=[d]), ("single_choice",))
        self.assertEqual(r.drafts, [])
        self.assertEqual(r.skipped, {("not_allowed_in_set", "multiple_choice"): 1})


class DetectTests(SimpleTestCase):
    def test_text_simple(self):
        r = detect.read_text("F: Frage?\n* a\n- b\n")
        self.assertEqual(r.format, "simple")
        self.assertEqual(len(r.drafts), 1)

    def test_text_gift(self):
        r = detect.read_text("::T:: Frage? {=a ~b}\n")
        self.assertEqual(r.format, "gift")
        self.assertEqual(len(r.drafts), 1)

    def test_detection_prefers_simple_when_f_prefix_present(self):
        text = "F: Welche Menge ist {1,2,3}?\n* diese\n- keine\n\nq: Nennen Sie ein Element aus {1,2,3}\n"
        self.assertTrue(gift.looks_like_gift(text))  # precondition: braces look like GIFT
        r = detect.read_text(text)
        self.assertEqual(r.format, "simple")
        self.assertEqual([d["kind"] for d in r.drafts], ["single_choice", "open_text"])
        self.assertIn("{1,2,3}", r.drafts[0]["text"])
        self.assertIn("{1,2,3}", r.drafts[1]["text"])

    def test_text_without_markers_is_simple(self):
        r = detect.read_text("irgendein Text")
        self.assertEqual(r.format, "simple")
        self.assertEqual(r.drafts, [])

    def test_upload_utf8_bom(self):
        r = detect.read_upload("\ufeffF: Größe?\n* groß\n- klein".encode(), "fragen.txt")
        self.assertIn("Größe", r.drafts[0]["text"])

    def test_cp1252_upload_umlauts(self):
        r = detect.read_upload("F: Größe?\n* groß\n- klein".encode("cp1252"), "fragen.txt")
        self.assertEqual(r.format, "simple")
        self.assertIn("Größe", r.drafts[0]["text"])
        self.assertEqual(opts(r.drafts[0]), ["groß", "klein"])

    def test_undecodable_bytes_and_nul_do_not_crash(self):
        r = detect.read_upload(b"F: a\x81b\x00c?\n* x\n- y", "f.txt")
        self.assertNotIn("\x00", r.drafts[0]["text"])

    def test_upload_gift_file(self):
        r = detect.read_upload(b"Frage? {=a ~b}", "moodle.gift")
        self.assertEqual(r.format, "gift")

    def test_upload_h5p(self):
        data = make_zip({
            "h5p.json": json.dumps({"mainLibrary": "H5P.MultiChoice 1.16"}),
            "content/content.json": json.dumps(mc()),
        })
        r = detect.read_upload(data, "quiz.h5p")
        self.assertEqual(r.format, "h5p")
        self.assertEqual(len(r.drafts), 1)

    def test_upload_ilias_zip_and_xml(self):
        xml = fixture("ilias_legacy_qti.xml")
        r = detect.read_upload(make_zip({"1__0__qpl_2/1__0__qti_2.xml": xml}), "pool.zip")
        self.assertEqual(r.format, "ilias")
        self.assertTrue(r.drafts)
        r = detect.read_upload(xml, "1__0__qti_2.xml")
        self.assertEqual(r.format, "ilias")
        r = detect.read_upload(xml, "export")  # sniffed without extension
        self.assertEqual(r.format, "ilias")

    def test_broken_zip_fails(self):
        with self.assertRaises(ImportFailed):
            detect.read_upload(b"PK\x03\x04kaputt", "x.zip")
        with self.assertRaises(ImportFailed):
            detect.read_upload(b"kein zip", "x.h5p")

    def test_zip_without_questions_fails(self):
        with self.assertRaises(ImportFailed):
            detect.read_upload(make_zip({"readme.txt": "hi"}), "x.zip")


class ReviewFixTests(SimpleTestCase):
    """Findings of the final branch review (#323)."""

    # -- simple format: markers need whitespace (finding 4) -----------------

    def test_marker_without_space_is_text(self):
        r = simple.parse("F: Wie kalt?\n-5 Grad\n3.14 ist Pi\n* ja\n- nein\n")
        (d,) = r.drafts
        self.assertEqual(opts(d), ["ja", "nein"])
        self.assertIn("-5 Grad", d["text"])
        self.assertIn("3.14 ist Pi", d["text"])

    def test_number_marker_without_space_after_options_is_invalid(self):
        r = simple.parse("F: Reihenfolge\n1. a\n2. b\n3.14 ist Pi\n")
        self.assertEqual(r.drafts, [])
        self.assertEqual(r.skipped, {("invalid", "Zeile 1"): 1})

    def test_bare_marker_is_invalid(self):
        for marker in ("-", "*", "1.", "2)"):
            r = simple.parse(f"F: Frage\n* a\n{marker}\n- b\n")
            self.assertEqual(r.drafts, [], marker)
            self.assertEqual(r.skipped, {("invalid", "Zeile 1"): 1}, marker)

    def test_tab_after_marker(self):
        r = simple.parse("F: Frage\n*\ta\n-\tb\n")
        self.assertEqual(opts(r.drafts[0]), ["a", "b"])

    def test_multi_marker_with_trailing_whitespace(self):
        r = simple.parse("F: Frage [mehrfach]   \t\n* a\n- b\n")
        self.assertEqual(r.drafts[0]["kind"], "multiple_choice")
        self.assertEqual(r.drafts[0]["text"], "<p>Frage</p>")

    def test_simple_too_many_options(self):
        lines = "".join(f"- o{i}\n" for i in range(core.MAX_OPTIONS + 1))
        r = simple.parse("F: Frage\n* a\n" + lines)
        self.assertEqual(r.drafts, [])
        self.assertEqual(r.skipped, {("too_many_options", ""): 1})

    # -- GIFT (findings 3, 7, title regex) ----------------------------------

    def test_gift_image_not_reported_for_skipped_question(self):
        for body in ("{#1:0.5}", "{=a -> 1 =b -> 2}"):
            r = gift.parse(f'[html]Siehe <img src="x.png"> Bild {body}')
            self.assertEqual(r.drafts, [], body)
            self.assertNotIn(("image_dropped", ""), r.skipped, body)

    def test_gift_nbsp_becomes_space(self):
        r = gift.parse("Frage\xa0eins? {=a ~b}")
        self.assertEqual(r.drafts[0]["text"], "<p>Frage eins?</p>")

    def test_gift_title_ending_in_backslash(self):
        r = gift.parse("::Titel\\::Frage? {=a ~b}")
        self.assertEqual(r.drafts[0]["text"], "<p>Frage?</p>")

    def test_gift_too_many_options(self):
        answers = " ".join(f"~o{i}" for i in range(core.MAX_OPTIONS + 1))
        r = gift.parse("Frage? {=a " + answers + "}")
        self.assertEqual(r.drafts, [])
        self.assertEqual(r.skipped, {("too_many_options", ""): 1})

    # -- H5P (findings 2, 3) -------------------------------------------------

    def test_h5p_string_false_is_not_correct(self):
        content = mc(answers=(("A", "true"), ("B", "false"), ("C", False)))
        r = h5p.parse(h5p_zip("H5P.MultiChoice 1.16", content))
        self.assertEqual(correct(r.drafts[0]), ["A"])
        self.assertEqual(r.drafts[0]["kind"], "single_choice")

    def test_h5p_image_not_reported_for_skipped_question(self):
        img = '<p>Q <img src="a.png"></p>'
        r = h5p.parse(h5p_zip("H5P.MultiChoice 1.16", mc(question=img, answers=(("A", False), ("B", False)))))
        self.assertEqual(r.drafts, [])
        self.assertEqual(r.skipped, {("invalid", "H5P.MultiChoice"): 1})
        r = h5p.parse(h5p_zip("H5P.TrueFalse 1.8", {"question": img, "correct": "maybe"}))
        self.assertEqual(r.skipped, {("invalid", "H5P.TrueFalse"): 1})

    def test_h5p_image_and_media_counted_once(self):
        media = {"type": {"library": "H5P.Image 1.1", "params": {}}}
        r = h5p.parse(h5p_zip(
            "H5P.TrueFalse 1.8", {"question": '<p>Q <img src="a.png"></p>', "correct": "true", "media": media},
        ))
        self.assertEqual(len(r.drafts), 1)
        self.assertEqual(r.skipped, {("image_dropped", ""): 1})

    def test_h5p_too_many_answers_bail_out(self):
        answers = [("A", True)] + [(f"o{i}", False) for i in range(50_000)]
        r = h5p.parse(h5p_zip("H5P.MultiChoice 1.16", mc(answers=answers)))
        self.assertEqual(r.drafts, [])
        self.assertEqual(r.skipped, {("too_many_options", ""): 1})

    # -- finalize: image notice only for kept questions (finding 3) ----------

    def test_finalize_withdraws_image_notice_of_dropped_question(self):
        essay = {"taskDescription": '<p>Q <img src="a.png"></p>'}
        r = h5p.parse(h5p_zip("H5P.Essay 1.5", essay))
        self.assertEqual(r.skipped, {("image_dropped", ""): 1})
        finalize(r, ("single_choice",))
        self.assertEqual(r.drafts, [])
        self.assertEqual(r.skipped, {("not_allowed_in_set", "open_text"): 1})

    def test_finalize_keeps_image_notice_and_removes_marker(self):
        r = gift.parse('[html]Siehe <img src="x.png"> Bild {=a ~b}\n\n[html]Noch <img src="y.png"> {}')
        finalize(r, ("single_choice",))
        self.assertEqual(len(r.drafts), 1)
        self.assertNotIn(core.IMAGE_FLAG, r.drafts[0])
        self.assertEqual(
            r.skipped, {("image_dropped", ""): 1, ("not_allowed_in_set", "open_text"): 1}
        )

    def test_finalize_over_limit_withdraws_image_notice(self):
        r = ImportResult(format="gift")
        for i in range(core.MAX_QUESTIONS + 1):
            r.add(draft(text=f"<p>{i}</p>"), image_dropped=i == core.MAX_QUESTIONS)
        finalize(r, ALL)
        self.assertEqual(len(r.drafts), core.MAX_QUESTIONS)
        self.assertEqual(r.skipped, {("over_limit", ""): 1})

    # -- ILIAS ---------------------------------------------------------------

    def test_ilias_too_many_labels_bail_out(self):
        labels = tuple(f"o{i}" for i in range(core.MAX_OPTIONS + 1))
        r = ilias.parse_xml(qti(qti_item(response=choice_response(labels=labels), resprocessing=cond(0, 1))))
        self.assertEqual(r.drafts, [])
        self.assertEqual(r.skipped, {("too_many_options", ""): 1})

    def test_ilias_negated_and_response_scoping_kept(self):
        response = choice_response(labels=("A", "B", "C"))
        r = ilias.parse_xml(qti(qti_item(
            qtype="MULTIPLE CHOICE QUESTION",
            question="<mattext>Q?</mattext><matimage label='q.png'/>",
            response=response,
            resprocessing=cond(0, 1) + cond(1, 1, negate=True) + cond(2, 1),
        )))
        (d,) = r.drafts
        self.assertEqual(d["text"], "<p>Q?</p>")
        self.assertEqual(correct(d), ["A", "C"])
        self.assertEqual(r.skipped, {("image_dropped", ""): 1})

    # -- text cap ------------------------------------------------------------

    def test_text_over_cap_fails(self):
        with self.assertRaises(ImportFailed):
            detect.read_text("x" * (detect.TEXT_MAX_CHARS + 1))
        with self.assertRaises(ImportFailed):
            detect.read_upload(b"x" * (detect.TEXT_MAX_CHARS + 1), "fragen.txt")

    # -- plain(): unchanged tag semantics ------------------------------------

    def test_plain_keeps_tag_semantics(self):
        self.assertEqual(core.plain('a <img alt="<" src="x"> b'), "a  b")
        self.assertEqual(core.plain("a < b"), "a < b")
        self.assertEqual(core.plain("<b>x</b> < y"), "x < y")
        self.assertEqual(core.strip_images('<IMG src=x>a<img'), "a<img")


class RegexComplexityTests(SimpleTestCase):
    """~1 MB inputs that made quadratic/exponential patterns stall the single
    backend process (#323 review). Each must finish well within LIMIT."""

    N = 1_000_000
    LIMIT = 2.0

    def assertFast(self, fn, label):
        import time
        start = time.perf_counter()
        fn()
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, self.LIMIT, f"{label} took {elapsed:.2f}s")

    def test_read_text(self):
        n = self.N
        cases = {
            "newlines": "\n" * n,
            "spaces": " " * n,
            "lt": "<" * n,
            "multi marker after spaces": "F: a" + " " * (n - 10) + "b",
            "gift title backslashes": "::" + "\\" * (n - 20) + "x {=a ~b}",
            "gift title lines": "::\n" * (n // 3),
            "F lines": "F:\n" * (n // 3),
        }
        for label, text in cases.items():
            self.assertFast(lambda text=text: detect.read_text(text), label)
        self.assertFast(lambda: gift.looks_like_gift("\n" * n), "gift title line on newlines")

    def test_h5p(self):
        n = self.N
        for label, content in {
            "lt in answer": {"question": "<p>Q</p>", "answers": [
                {"text": "<" * n, "correct": True}, {"text": "B", "correct": False},
            ]},
            "lt in question": mc(question="<" * n),
            "img in question": mc(question="<img " * (n // 5)),
            "newlines in question and answer": {"question": "\n" * n, "answers": [
                {"text": "\n" * n, "correct": True}, {"text": "B", "correct": False},
            ]},
            "spaces in question and answer": {"question": " " * n, "answers": [
                {"text": " " * n, "correct": True}, {"text": "B", "correct": False},
            ]},
        }.items():
            zf = h5p_zip("H5P.MultiChoice 1.16", content)
            self.assertFast(lambda zf=zf: h5p.parse(zf), label)
        for ws in ("\n", " "):
            essay = {"taskDescription": ws * n, "solution": {"sample": ws * n}}
            zf = h5p_zip("H5P.Essay 1.5", essay)
            self.assertFast(lambda zf=zf: h5p.parse(zf), f"essay {ws!r}")

    def test_ilias(self):
        n = self.N
        for label, xml in {
            "lt in label": qti(qti_item(
                response=choice_response(labels=('<mattext texttype="text/xhtml">' + "&lt;" * (n // 4) + "</mattext>", "B")),
                resprocessing=cond(0, 1),
            )),
            "img in question": qti(qti_item(
                question='<mattext texttype="text/xhtml">' + "&lt;img " * (n // 8) + "</mattext>",
                response=choice_response(), resprocessing=cond(0, 1),
            )),
            "deep and wide": qti(qti_item(
                qtype="TEXT QUESTION",
                question="<x>" * 200 + "<mattext>a</mattext>" * (n // 20) + "</x>" * 200,
            )),
            "newlines and spaces": qti(qti_item(
                question="<mattext>" + "\n" * (n // 2) + "</mattext>"
                + '<mattext texttype="text/xhtml">' + " " * (n // 2) + "</mattext>",
                response=choice_response(labels=(
                    "\n" * (n // 4) + "A", '<mattext texttype="text/xhtml">' + " " * (n // 4) + "B</mattext>",
                )),
                resprocessing=cond(0, 1),
            )),
            "many labels": qti(qti_item(
                qtype="ORDERING QUESTION",
                response=choice_response(labels=tuple("o" for _ in range(n // 100))),
            )),
        }.items():
            self.assertFast(lambda xml=xml: ilias.parse_xml(xml), label)


# -- images kept via side-channel (#336) ---------------------------------------

def png(color=(255, 0, 0)) -> bytes:
    """A tiny self-made PNG (no third-party file)."""
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), color).save(buf, "PNG")
    return buf.getvalue()


def h5p_media(path="images/a.png", alt="Bild", decorative=False, metadata=None, copyright=None):
    file = {"path": path, "mime": "image/png"}
    if copyright is not None:
        file["copyright"] = copyright
    media = {"type": {
        "library": "H5P.Image 1.1",
        "params": {"file": file, "alt": alt, "decorative": decorative},
    }}
    if metadata is not None:
        media["type"]["metadata"] = metadata
    return media


PH1 = IMPORT_IMAGE_PREFIX + "1"
PH2 = IMPORT_IMAGE_PREFIX + "2"


class H5PImageTests(SimpleTestCase):
    def test_h5p_media_image_kept_with_credit(self):
        r = h5p.parse(safezip.open_zip(fixture("multichoice-image.h5p")))
        [d] = r.drafts
        self.assertTrue(d["text"].startswith(f'<p><img src="{PH1}"'), d["text"])
        self.assertIn("Welche Farbe hat die Fläche?", d["text"])
        self.assertEqual(r.skipped, {})
        self.assertEqual(list(r.images), [PH1])
        img = r.images[PH1]
        self.assertTrue(img.data.startswith(b"\x89PNG"))
        self.assertEqual(img.alt, "Rote Fläche")
        self.assertIn('alt="Rote Fläche"', d["text"])
        self.assertEqual(img.credit, {
            "author": "Karen Jackson",
            "title": "Rotes Quadrat",
            "source": "https://example.org/bild",
            "license": "cc-by-nd",
            "version": "4.0",
            "text": "",
        })
        self.assertTrue(img.filename.isascii())
        self.assertTrue(img.filename.endswith(".png"))
        finalize(r, ALL)
        self.assertEqual(len(r.drafts), 1)
        self.assertEqual(r.skipped, {})

    def test_h5p_license_unknown_no_credit(self):
        for media in (
            h5p_media(copyright={"license": "U"}),
            h5p_media(metadata={"license": "U", "authors": []}),
            h5p_media(),
        ):
            r = h5p.parse(h5p_zip("H5P.MultiChoice 1.16", mc(media=media), {"content/images/a.png": png()}))
            self.assertEqual(r.skipped, {})
            self.assertEqual(r.images[PH1].credit, {})

    def test_h5p_old_copyright_credit(self):
        media = h5p_media(copyright={
            "license": "CC BY-SA", "version": "3.0", "author": "Max Muster", "title": "Turm", "source": "",
        })
        r = h5p.parse(h5p_zip("H5P.MultiChoice 1.16", mc(media=media), {"content/images/a.png": png()}))
        self.assertEqual(r.images[PH1].credit, {
            "author": "Max Muster", "title": "Turm", "source": "", "license": "cc-by-sa", "version": "3.0", "text": "",
        })

    def test_h5p_title_only_metadata_falls_back_to_copyright(self):
        media = h5p_media(
            metadata={"title": "Image", "license": "U"},
            copyright={"license": "CC BY", "version": "4.0", "author": "Max Muster"},
        )
        r = h5p.parse(h5p_zip("H5P.MultiChoice 1.16", mc(media=media), {"content/images/a.png": png()}))
        self.assertEqual(r.images[PH1].credit["author"], "Max Muster")
        self.assertEqual(r.images[PH1].credit["license"], "cc-by")
        # Title only and nothing else: kept as is (shows no credit line).
        media = h5p_media(metadata={"title": "Image", "license": "U"})
        r = h5p.parse(h5p_zip("H5P.MultiChoice 1.16", mc(media=media), {"content/images/a.png": png()}))
        self.assertEqual(r.images[PH1].credit["title"], "Image")
        self.assertEqual(r.images[PH1].credit["license"], "")
        self.assertEqual(r.images[PH1].credit["author"], "")

    def test_h5p_option_text_without_image_verbatim(self):
        content = {"choices": [{"question": "<p>Q</p>", "answers": ["a<b", "c"]}]}
        r = h5p.parse(h5p_zip("H5P.SingleChoiceSet 1.11", content))
        self.assertEqual(opts(r.drafts[0]), ["a<b", "c"])

    def test_h5p_decorative_empty_alt(self):
        media = h5p_media(alt="Hübsch", decorative=True)
        r = h5p.parse(h5p_zip("H5P.MultiChoice 1.16", mc(media=media), {"content/images/a.png": png()}))
        self.assertEqual(r.images[PH1].alt, "")
        self.assertTrue(r.drafts[0]["text"].startswith(f'<p><img src="{PH1}" alt=""'), r.drafts[0]["text"])

    def test_h5p_missing_image_file_dropped(self):
        r = h5p.parse(h5p_zip("H5P.MultiChoice 1.16", mc(question='<p>Q <img src="images/none.png"></p>')))
        [d] = r.drafts
        self.assertNotIn("<img", d["text"])
        self.assertEqual(r.images, {})
        self.assertEqual(r.skipped, {("image_dropped", ""): 1})

    def test_h5p_inline_image_kept(self):
        r = h5p.parse(h5p_zip(
            "H5P.MultiChoice 1.16", mc(question='<p>Q <img src="images/b.png" alt="Turm"> ?</p>'),
            {"content/images/b.png": png()},
        ))
        self.assertEqual(r.drafts[0]["text"], f'<p>Q <img src="{PH1}" alt="Turm"> ?</p>')
        self.assertEqual(r.skipped, {})

    def test_h5p_same_image_twice_one_entry(self):
        question = '<p><img src="images/a.png"> und <img src="images/a.png"></p>'
        r = h5p.parse(h5p_zip(
            "H5P.MultiChoice 1.16", mc(question=question, media=h5p_media()), {"content/images/a.png": png()},
        ))
        self.assertEqual(list(r.images), [PH1])
        self.assertEqual(r.drafts[0]["text"].count(f'src="{PH1}"'), 3)
        self.assertEqual(r.skipped, {})

    def test_h5p_answer_image_becomes_option_image(self):
        content = mc(answers=(('A <img src="images/a.png">', True), ('<img src="images/b.png">', False)))
        r = h5p.parse(h5p_zip(
            "H5P.MultiChoice 1.16", content,
            {"content/images/a.png": png(), "content/images/b.png": png((0, 0, 255))},
        ))
        [d] = r.drafts
        self.assertEqual(d["options"], [
            {"text": "A", "is_correct": True, "image": PH1},
            {"text": "", "is_correct": False, "image": PH2},
        ])
        self.assertEqual(r.skipped, {})
        finalize(r, ALL)
        self.assertEqual(len(r.drafts), 1)

    def test_h5p_answer_image_alt_carried_to_option(self):
        content = mc(answers=(
            ('<img src="images/a.png" alt="Ein roter Kreis">', True),
            ('B <img src="images/b.png">', False),
        ))
        r = h5p.parse(h5p_zip(
            "H5P.MultiChoice 1.16", content,
            {"content/images/a.png": png(), "content/images/b.png": png((0, 0, 255))},
        ))
        [d] = r.drafts
        self.assertEqual(d["options"][0].get("image_alt"), "Ein roter Kreis")
        self.assertNotIn("image_alt", d["options"][1])

    def test_h5p_dropped_answer_image_has_no_alt(self):
        content = mc(answers=(("A", True), ('B <img src="images/none.png" alt="weg">', False)))
        r = h5p.parse(h5p_zip("H5P.MultiChoice 1.16", content))
        [d] = r.drafts
        self.assertNotIn("image_alt", d["options"][1])
        self.assertNotIn("image", d["options"][1])

    def test_h5p_answer_image_missing_and_no_text_invalid(self):
        content = mc(answers=(("A", True), ('<img src="images/none.png">', False)))
        r = h5p.parse(h5p_zip("H5P.MultiChoice 1.16", content))
        self.assertEqual(r.drafts, [])
        self.assertEqual(r.skipped, {("invalid", "H5P.MultiChoice"): 1})

    def test_h5p_non_image_media_dropped(self):
        media = {"type": {"library": "H5P.Video 1.6", "params": {"sources": [{"path": "videos/a.mp4"}]}}}
        r = h5p.parse(h5p_zip("H5P.MultiChoice 1.16", mc(media=media)))
        self.assertEqual(len(r.drafts), 1)
        self.assertEqual(r.images, {})
        self.assertEqual(r.skipped, {("image_dropped", ""): 1})

    def test_path_traversal_image_rejected(self):
        for question, media in (
            ('<p>Q <img src="../../etc/x.png"></p>', None),
            ("<p>Q</p>", h5p_media(path="../../etc/x.png")),
            ("<p>Q</p>", h5p_media(path="../h5p.json")),
            ('<p>Q <img src="/etc/x.png"></p>', None),
            ('<p>Q <img src="https://evil.example/x.png"></p>', None),
            ('<p>Q <img src="data:image/png;base64,iVBORw0KGgo="></p>', None),
        ):
            extra = {"media": media} if media else {}
            r = h5p.parse(h5p_zip("H5P.MultiChoice 1.16", mc(question=question, **extra)))
            [d] = r.drafts
            self.assertNotIn("<img", d["text"], question)
            self.assertEqual(r.images, {}, question)
            self.assertEqual(r.skipped, {("image_dropped", ""): 1}, question)

    def test_literal_media_src_in_package_dropped(self):
        """A package must not reference placeholders or this instance's files."""
        for src in (PH1, "/media/question-images/2026/11/x.webp"):
            r = h5p.parse(h5p_zip("H5P.MultiChoice 1.16", mc(question=f'<p>Q <img src="{src}"></p>')))
            self.assertNotIn("<img", r.drafts[0]["text"], src)
            self.assertEqual(r.skipped, {("image_dropped", ""): 1}, src)

    def test_image_cap_100(self):
        n = core.MAX_IMPORT_IMAGES + 1
        questions = [
            {"library": "H5P.MultiChoice 1.16", "params": mc(question=f'<p>Q{i} <img src="images/{i}.png"></p>')}
            for i in range(n)
        ]
        files = {f"content/images/{i}.png": png() for i in range(n)}
        r = h5p.parse(h5p_zip("H5P.QuestionSet 1.20", {"questions": questions}, files))
        self.assertEqual(len(r.drafts), n)
        self.assertEqual(len(r.images), core.MAX_IMPORT_IMAGES)
        self.assertEqual(r.skipped, {("image_dropped", ""): 1})
        self.assertNotIn("<img", r.drafts[-1]["text"])

    def test_image_of_skipped_question_not_counted(self):
        r = h5p.parse(h5p_zip("H5P.Essay 1.5", {"taskDescription": '<p>Q <img src="images/x.png"></p>'}))
        finalize(r, ("single_choice",))
        self.assertEqual(r.drafts, [])
        self.assertEqual(r.skipped, {("not_allowed_in_set", "open_text"): 1})


class IliasImageTests(SimpleTestCase):
    B64 = "iVBORw0KGgo="

    def test_ilias_base64_matimage_kept(self):
        r = ilias.parse_xml(qti(qti_item(
            question=f'<mattext>Q?</mattext><matimage imagtype="image/png" label="q.png" embedded="base64">{self.B64}</matimage>',
            response=choice_response(), resprocessing=cond(0, 1),
        )))
        [d] = r.drafts
        self.assertEqual(d["text"], f'<p>Q?</p><p><img src="{PH1}" alt=""></p>')
        self.assertEqual(r.images[PH1].data, b"\x89PNG\r\n\x1a\n")
        self.assertEqual(r.images[PH1].credit, {})
        self.assertEqual(r.skipped, {})

    def test_ilias_broken_base64_dropped(self):
        r = ilias.parse_xml(qti(qti_item(
            question='<mattext>Q?</mattext><matimage label="q.png" embedded="base64">!!!x</matimage>',
            response=choice_response(), resprocessing=cond(0, 1),
        )))
        self.assertEqual(r.images, {})
        self.assertEqual(r.skipped, {("image_dropped", ""): 1})

    def test_ilias_uri_matimage_from_zip(self):
        data = make_zip({
            "1_0_tst_5/1_0_qti_5.xml": fixture("ilias_trunk_test_qti.xml"),
            "1_0_tst_5/objects/il_0_mob_77/katze.png": png(),
        })
        r = ilias.parse(safezip.open_zip(data))
        d = r.drafts[0]
        # The inline <img src="il_0_mob_77"> and its matimage are one image.
        self.assertEqual(d["text"].count("<img"), 1)
        self.assertIn(f'src="{PH1}"', d["text"])
        self.assertNotIn("il_0_mob", d["text"])
        self.assertEqual(r.images[PH1].data, png())
        self.assertNotIn(("image_dropped", ""), r.skipped)

    def test_ilias_uri_option_image_from_zip(self):
        response = (
            '<response_lid ident="MCSR"><render_choice>'
            '<response_label ident="0"><material><mattext>A</mattext></material></response_label>'
            '<response_label ident="1"><material><matimage label="b.png" uri="objects/b.png"/></material></response_label>'
            "</render_choice></response_lid>"
        )
        data = make_zip({"x/x_qti_1.xml": qti(qti_item(response=response, resprocessing=cond(0, 1))),
                         "x/objects/b.png": png()})
        r = ilias.parse(safezip.open_zip(data))
        [d] = r.drafts
        self.assertEqual(d["options"][1], {"text": "", "is_correct": False, "image": PH1})
        self.assertEqual(r.skipped, {})

    def test_ilias_option_image_alt_carried(self):
        response = (
            '<response_lid ident="MCSR"><render_choice>'
            '<response_label ident="0"><material><mattext texttype="text/xhtml">&lt;img src="il_0_mob_5" alt="Eine Katze"&gt;</mattext>'
            '<matimage label="il_0_mob_5" uri="objects/a.png"/></material></response_label>'
            '<response_label ident="1"><material><matimage label="b.png" uri="objects/b.png" alt="Ein Hund"/></material></response_label>'
            '<response_label ident="2"><material><mattext>C</mattext><matimage label="c.png" uri="objects/c.png"/></material></response_label>'
            "</render_choice></response_lid>"
        )
        data = make_zip({"x/x_qti_1.xml": qti(qti_item(response=response, resprocessing=cond(0, 1))),
                         "x/objects/a.png": png(), "x/objects/b.png": png((0, 0, 255)),
                         "x/objects/c.png": png((0, 255, 0))})
        r = ilias.parse(safezip.open_zip(data))
        [d] = r.drafts
        self.assertEqual([o.get("image_alt") for o in d["options"]], ["Eine Katze", "Ein Hund", None])

    def test_ilias_option_inline_img_and_matimage_one_image(self):
        response = (
            '<response_lid ident="MCSR"><render_choice>'
            '<response_label ident="0"><material><mattext>A</mattext></material></response_label>'
            '<response_label ident="1"><material><mattext texttype="text/xhtml">&lt;p&gt;B '
            '&lt;img src="il_0_mob_5"&gt;&lt;/p&gt;</mattext>'
            '<matimage label="il_0_mob_5" uri="objects/il_0_mob_5/b.png"/></material></response_label>'
            "</render_choice></response_lid>"
        )
        data = make_zip({"x/x_qti_1.xml": qti(qti_item(response=response, resprocessing=cond(0, 1))),
                         "x/objects/il_0_mob_5/b.png": png()})
        r = ilias.parse(safezip.open_zip(data))
        [d] = r.drafts
        self.assertEqual(d["options"][1], {"text": "B", "is_correct": False, "image": PH1})
        self.assertEqual(list(r.images), [PH1])
        self.assertEqual(r.skipped, {})

    def test_ilias_xml_uri_image_dropped(self):
        r = ilias.parse_xml(qti(qti_item(
            question='<mattext>Q?</mattext><matimage label="q.png" uri="objects/q.png"/>',
            response=choice_response(), resprocessing=cond(0, 1),
        )))
        [d] = r.drafts
        self.assertEqual(d["text"], "<p>Q?</p>")
        self.assertEqual(r.images, {})
        self.assertEqual(r.skipped, {("image_dropped", ""): 1})

    def test_ilias_uri_traversal_dropped(self):
        data = make_zip({"x/x_qti_1.xml": qti(qti_item(
            question='<mattext>Q?</mattext><matimage label="q.png" uri="../../etc/x.png"/>',
            response=choice_response(), resprocessing=cond(0, 1),
        ))})
        r = ilias.parse(safezip.open_zip(data))
        self.assertEqual(r.images, {})
        self.assertEqual(r.skipped, {("image_dropped", ""): 1})


class ImportImageCoreTests(SimpleTestCase):
    def test_gift_still_drops_images(self):
        r = gift.parse('[html]Siehe <img src="x.png"> Bild {=a ~b}')
        self.assertNotIn("<img", r.drafts[0]["text"])
        self.assertEqual(r.images, {})
        self.assertEqual(r.skipped, {("image_dropped", ""): 1})

    def test_placeholder_survives_sanitizer(self):
        html = f'<p><img src="{PH1}" alt="a"></p>'
        self.assertEqual(clean_html(html), html)
        self.assertEqual(clean_media_url(IMPORT_IMAGE_PREFIX + "100"), IMPORT_IMAGE_PREFIX + "100")

    def test_add_image_dedupes_by_key(self):
        r = ImportResult(format="h5p")
        self.assertEqual(r.add_image(core.ImportImage(b"a", "a.png"), key="content/a.png"), PH1)
        self.assertEqual(r.add_image(core.ImportImage(b"a", "a.png"), key="content/a.png"), PH1)
        self.assertEqual(r.add_image(core.ImportImage(b"b", "b.png")), PH2)
        self.assertEqual(list(r.images), [PH1, PH2])

    def test_clean_keeping_images(self):
        seen = []

        def resolve(src):
            seen.append(src)
            return PH1 if src == "ok.png" else ""

        html, dropped = core.clean_keeping_images(
            '<p>A <img src="ok.png" alt="x &quot;y&quot;" onerror="x()"> <img src="bad.png"></p>', resolve,
        )
        self.assertEqual(html, f'<p>A <img src="{PH1}" alt="x &quot;y&quot;"> </p>')
        self.assertTrue(dropped)
        self.assertEqual(seen, ["ok.png", "bad.png"])
        self.assertEqual(core.clean_keeping_images("<p>ohne</p>", resolve), ("<p>ohne</p>", False))

    def test_clean_keeping_images_obfuscated(self):
        for markup in ('<im<img>g src="ok.png">', '<image src="ok.png">', f'<im<img>g src="{PH1}">'):
            html, dropped = core.clean_keeping_images(f"<p>Q {markup}</p>", lambda src: "")
            self.assertNotIn("<img", html, markup)
            self.assertTrue(dropped, markup)

    def test_h5p_credit_mapping(self):
        meta = {"authors": [{"name": "A"}, {"name": "B"}], "title": "T"}
        table = [
            ("CC BY", "4.0", "", {"license": "cc-by", "version": "4.0", "text": ""}),
            ("CC BY-SA", "3.0", "", {"license": "cc-by-sa", "version": "3.0", "text": ""}),
            ("CC BY-ND", "4.0", "", {"license": "cc-by-nd", "version": "4.0", "text": ""}),
            ("CC BY-NC", "2.5", "", {"license": "cc-by-nc", "version": "2.5", "text": ""}),
            ("CC BY-NC-SA", "4.0", "", {"license": "cc-by-nc-sa", "version": "4.0", "text": ""}),
            ("CC BY-NC-ND", "4.0", "", {"license": "cc-by-nc-nd", "version": "4.0", "text": ""}),
            ("CC BY", "v4", "", {"license": "cc-by", "version": "", "text": ""}),
            ("CC0 1.0", "", "", {"license": "cc0", "version": "", "text": ""}),
            ("CC PDM", "", "", {"license": "pd", "version": "", "text": ""}),
            ("PD", "CC0 1.0", "", {"license": "pd", "version": "", "text": ""}),
            ("C", "", "", {"license": "arr", "version": "", "text": ""}),
            ("C", "", "Nur Lehre", {"license": "arr", "version": "", "text": "Nur Lehre"}),
            ("CC BY", "4.0", "Extra", {"license": "cc-by", "version": "4.0", "text": ""}),
            ("U", "", "", {"license": "", "version": "", "text": ""}),
            ("", "", "", {"license": "", "version": "", "text": ""}),
            ("GNU GPL", "v3", "", {"license": "", "version": "", "text": ""}),
        ]
        for code, version, extras, expected in table:
            credit = licenses.h5p_credit(meta, code, version, extras)
            self.assertEqual(
                credit, {"author": "A, B", "title": "T", "source": "", **expected}, code,
            )
        long = licenses.h5p_credit({}, "C", "", "x" * 300)
        self.assertEqual(len(long["text"]), 100)
        # All rights reserved without author: still a credit (license set).
        self.assertEqual(licenses.h5p_credit({}, "C", "", "")["license"], "arr")
        self.assertEqual(licenses.h5p_credit({}, "U", "", ""), {})
        self.assertEqual(licenses.h5p_credit({}, None, None, None), {})

    def test_h5p_credit_tolerates_garbage(self):
        for meta in ({"authors": "x"}, {"authors": [1, None, {"name": 5}]}, {"title": 3, "source": []}, None):
            self.assertEqual(licenses.h5p_credit(meta, ["CC BY"], 4, {}), {}, meta)
        credit = licenses.h5p_credit({"source": "javascript:alert(1)", "title": "T"}, "CC BY", "", "")
        self.assertEqual(credit["source"], "")
        credit = licenses.h5p_credit({"authors": [{"name": "x" * 300}]}, "CC BY", "", "")
        self.assertEqual(len(credit["author"]), 200)
