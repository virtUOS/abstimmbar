# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
import io
import json
import zipfile

from django.test import SimpleTestCase, override_settings

from rooms.question_import import gift, h5p, safezip, simple
from rooms.question_import.core import (
    ImportFailed,
    ImportResult,
    finalize,
    true_false_labels,
)

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
