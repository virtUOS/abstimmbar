# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Result aggregation, shared by the SSE snapshots (state.py), the
management results API and the CSV export."""
from collections import Counter

from django.db.models import Avg, Count, Max, Min

from common.i18n_fields import translated_map
from rooms.models import Question

from .models import Vote


def options_with_counts(run, question):
    """Per-option vote counts for a choice question.

    ``text`` is a {de, en} map (#33 MR2): the SSE hub broadcasts one payload
    to every participant, so it can't be resolved to a single language here.
    """
    # Recording mode (#53): split the per-option tally by vote source in one
    # grouped query — combined `count` plus `onsite`/`recording` breakdown.
    combined, onsite, recording = {}, {}, {}
    rows = (
        Vote.options.through.objects.filter(vote__run=run, vote__question=question)
        .values_list("answeroption", "vote__source")
        .annotate(n=Count("id"))
    )
    for option_id, source, n in rows:
        combined[option_id] = combined.get(option_id, 0) + n
        bucket = recording if source == Vote.Source.RECORDING else onsite
        bucket[option_id] = bucket.get(option_id, 0) + n
    return [
        {
            "id": option.pk,
            "text": translated_map(option, "text"),
            **({"image": option.image} if option.image else {}),
            "is_correct": option.is_correct,
            "is_abstention": option.is_abstention,
            "count": combined.get(option.pk, 0),
            "onsite": onsite.get(option.pk, 0),
            "recording": recording.get(option.pk, 0),
        }
        for option in question.options.all()
    ]


def likert_summary(options):
    """Diverging aggregation of an ordered Likert scale (v2 review feedback).

    `options` is the ``options_with_counts`` output for a Likert question —
    ordered by position and including any ``is_abstention`` entries.
    Abstentions are excluded from the scale and reported separately.

    The scale splits at its centre: an odd number of steps has a single
    neutral step in the middle; an even number has no neutral step and the
    divider sits between the two middle steps. ``divider`` is the position of
    that centre line as a percentage (0–100) of the scale width, so the
    frontend can draw the same line the presentation and results views share.

    Returns ``None`` when the shape is not a usable scale (< 2 real steps),
    so callers fall back to the plain per-option bars.
    """
    scale = [o for o in options if not o["is_abstention"]]
    abstentions = sum(o["count"] for o in options if o["is_abstention"])
    if len(scale) < 2:
        return None
    scale_total = sum(o["count"] for o in scale)
    n = len(scale)
    mid = n // 2
    neutral_index = mid if n % 2 else None

    def pct(count):
        return round(100 * count / scale_total, 1) if scale_total else 0.0

    steps = []
    for i, option in enumerate(scale):
        if i == neutral_index:
            polarity = "neutral"
        elif i < mid:
            polarity = "disagree"
        else:
            polarity = "agree"
        steps.append(
            {
                "id": option["id"],
                # Forwarded as-is from `options` — a {de, en} map (#33 MR2)
                # once that comes from options_with_counts.
                "text": option["text"],
                "count": option["count"],
                "pct": pct(option["count"]),
                "polarity": polarity,
            }
        )

    def total(polarity):
        return sum(s["count"] for s in steps if s["polarity"] == polarity)

    disagree, neutral, agree = total("disagree"), total("neutral"), total("agree")
    # Centre line from raw counts (not rounded pcts) to avoid display drift.
    lower = sum(o["count"] for o in scale[:mid])
    divider = 100 * lower / scale_total if scale_total else 50.0
    if neutral_index is not None and scale_total:
        divider += 100 * scale[neutral_index]["count"] / scale_total / 2

    return {
        "scale_total": scale_total,
        "abstentions": abstentions,
        "agree": agree,
        "agree_pct": pct(agree),
        "neutral": neutral,
        "neutral_pct": pct(neutral),
        "disagree": disagree,
        "disagree_pct": pct(disagree),
        "divider": round(divider, 1),
        "steps": steps,
    }


def words_with_counts(run, question, limit=150):
    """Word-cloud aggregation: case variants merge (review decision); the
    most frequent raw spelling wins the display."""
    votes = run.votes.filter(question=question).exclude(text="")
    groups = {}
    for text, source in votes.values_list("text", "source"):
        group = groups.setdefault(
            text.casefold(), {"variants": [], "onsite": 0, "recording": 0}
        )
        group["variants"].append(text)
        # Recording mode (#53): keep the source split per merged term.
        if source == Vote.Source.RECORDING:
            group["recording"] += 1
        else:
            group["onsite"] += 1
    words = [
        {
            "text": Counter(group["variants"]).most_common(1)[0][0],
            "count": len(group["variants"]),
            "onsite": group["onsite"],
            "recording": group["recording"],
        }
        for group in groups.values()
    ]
    words.sort(key=lambda w: -w["count"])
    return words[:limit]


def freetext_evaluation(run, question):
    """Live free-text evaluation summary (v2 KI): distinct answers grouped by
    the stored verdict along the question's chosen scale, plus how many answers
    are still being processed and whether to render a bar chart."""
    from .ai_freetext import clean_categories, middle_category

    categories = clean_categories(question.evaluation_categories)
    fallback = middle_category(categories)
    valid = {c.casefold(): c for c in categories}
    votes = run.votes.filter(question=question).exclude(text="")
    buckets = {verdict: {} for verdict in categories}
    pending = 0
    for text, verdict in votes.values_list("text", "ai_verdict"):
        if not verdict:
            pending += 1
            continue
        verdict = valid.get(verdict.casefold(), fallback)
        entry = buckets[verdict].setdefault(text.casefold(), {"text": text, "count": 0})
        entry["count"] += 1
    groups = [
        {
            "verdict": verdict,
            "count": sum(item["count"] for item in buckets[verdict].values()),
            "items": sorted(buckets[verdict].values(), key=lambda i: -i["count"]),
        }
        for verdict in categories
    ]
    return {
        "groups": groups,
        "categories": categories,
        "chart": question.evaluation_chart,
        "pending": pending,
        "total": votes.count(),
    }


def priority_stats(run, question):
    """Per-option average / min / max points for a ``priorities`` question
    (#58), sorted by average descending. ``text`` is a {de, en} map."""
    from .models import PriorityScore

    rows = (
        PriorityScore.objects.filter(vote__run=run, vote__question=question)
        .values("option")
        .annotate(avg=Avg("points"), min=Min("points"), max=Max("points"), n=Count("id"))
    )
    stats = {row["option"]: row for row in rows}
    result = []
    for option in question.options.all():
        row = stats.get(option.pk)
        result.append(
            {
                "id": option.pk,
                "text": translated_map(option, "text"),
                **({"image": option.image} if option.image else {}),
                "avg": round(row["avg"], 1) if row else 0,
                "min": row["min"] if row else 0,
                "max": row["max"] if row else 0,
                "n": row["n"] if row else 0,
            }
        )
    result.sort(key=lambda entry: entry["avg"], reverse=True)
    return result


# Minimum per-link relative-adjacency rate (%) for a pair of consecutive
# solution items to join a "correctly-ordered run" (brace) in the results.
ORDERING_CHAIN_THRESHOLD = 50.0


def ordering_stats(run, question):
    """Per-item correct-placement rate for an ``ordering`` question (#72).

    An item is "correctly placed" when the participant's assigned position for
    that option equals the option's own ``position`` (the authored solution).
    ``text`` is a {de, en} map. Items are returned in solution order; the extra
    ``full_correct_rate`` is the share of submissions matching the solution
    exactly. Rates are percentages rounded to 1 decimal.
    """
    from .models import OrderingResponse

    n = (
        run.votes.filter(question=question).count()
    )
    options = list(question.options.all())  # ordered by position (Meta.ordering)
    # correct count per option: assigned position == option.position
    correct_by_option = {}
    for option in options:
        correct_by_option[option.pk] = OrderingResponse.objects.filter(
            vote__run=run, vote__question=question,
            option=option, position=option.position,
        ).count()
    items = []
    for option in options:
        c = correct_by_option[option.pk]
        items.append(
            {
                "id": option.pk,
                "text": translated_map(option, "text"),
                **({"image": option.image} if option.image else {}),
                "correct_position": option.position + 1,
                "correct_rate": round(100.0 * c / n, 1) if n else 0,
                "n": n,
            }
        )
    # fully-correct submissions: every option placed at its own position.
    full_correct = 0
    if n:
        votes = run.votes.filter(question=question).prefetch_related("ordering_responses")
        solution = {o.pk: o.position for o in options}
        for vote in votes:
            if all(r.position == solution.get(r.option_id) for r in vote.ordering_responses.all()) \
               and vote.ordering_responses.count() == len(options):
                full_correct += 1
    # Relative-adjacency links + chains: load each submission's assigned
    # position per option once, then score consecutive solution pairs.
    subs = []  # [{option_id: assigned_position}, ...]
    if n:
        for vote in run.votes.filter(question=question).prefetch_related(
            "ordering_responses"
        ):
            subs.append({r.option_id: r.position for r in vote.ordering_responses.all()})

    def _adjacent(pos, a, b):
        return a.pk in pos and b.pk in pos and pos[b.pk] == pos[a.pk] + 1

    links = []
    for k in range(len(options) - 1):
        a, b = options[k], options[k + 1]
        hits = sum(1 for pos in subs if _adjacent(pos, a, b))
        links.append(
            {"from": a.pk, "to": b.pk, "rate": round(100.0 * hits / n, 1) if n else 0}
        )

    chains = []
    k = 0
    while k < len(links):
        if links[k]["rate"] >= ORDERING_CHAIN_THRESHOLD:
            start = k
            while k < len(links) and links[k]["rate"] >= ORDERING_CHAIN_THRESHOLD:
                k += 1
            end = k  # item index one past the last qualifying link
            whole = sum(
                1
                for pos in subs
                if all(_adjacent(pos, options[j], options[j + 1]) for j in range(start, end))
            )
            chains.append(
                {"start": start, "end": end, "rate": round(100.0 * whole / n, 1) if n else 0}
            )
        else:
            k += 1

    return {
        "items": items,
        "full_correct_rate": round(100.0 * full_correct / n, 1) if n else 0,
        "n": n,
        "links": links,
        "chains": chains,
    }


def run_results(run):
    """Full per-question aggregation of one run (management results view)."""
    questions = run.question_set.questions.prefetch_related("options")
    items = []
    for question in questions:
        item = {
            "id": question.pk,
            "position": question.position,
            "kind": question.kind,
            # {de, en} map (#33 MR2), matching item["options"][].text below so
            # the /results/ API contract is uniform maps throughout.
            "text": translated_map(question, "text"),
            "votes": run.votes.filter(question=question).count(),
            # Recording mode (#53): how many of this question's votes came from
            # recording viewers (async), so the view can show the split.
            "votes_recording": run.votes.filter(
                question=question, source=Vote.Source.RECORDING
            ).count(),
            # Vorher-Nachher-Paar (#54): the before-question this one mirrors,
            # so the results view can pair them for comparison (null otherwise).
            "before_question": question.before_question_id,
        }
        if question.kind in Question.TEXT_KINDS:
            item["words"] = words_with_counts(run, question)
            if question.kind == Question.Kind.OPEN_TEXT and question.ai_evaluate:
                item["evaluation"] = freetext_evaluation(run, question)
        elif question.kind == Question.Kind.PRIORITIES:
            item["priorities"] = priority_stats(run, question)
        elif question.kind == Question.Kind.ORDERING:
            item["ordering"] = ordering_stats(run, question)
        else:
            item["options"] = options_with_counts(run, question)
            if question.kind == Question.Kind.LIKERT:
                item["likert"] = likert_summary(item["options"])
        items.append(item)
    return {
        "run": run.pk,
        "phase": run.phase,
        "created_at": run.created_at.isoformat(),
        "first_opened_at": (
            run.first_opened_at.isoformat() if run.first_opened_at else None
        ),
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
        "votes_total": run.votes.count(),
        # Recording mode (#53): total async votes in this run; the view shows
        # the on-site/recording split only when there are any.
        "recording_votes": run.votes.filter(source=Vote.Source.RECORDING).count(),
        "questions": items,
    }
