"""Restart guard (§ 8): how much committee activity would a restart destroy?"""

from rooms.models import QuestionSet

from .models import Ballot


def activity() -> dict:
    """Running meetings and open secret ballots (their tallies live in RAM)."""
    return {
        "meetings_running": QuestionSet.objects.filter(
            type=QuestionSet.SetType.MEETING,
            meeting_state=QuestionSet.MeetingState.STARTED,
        ).count(),
        "secret_ballots_open": Ballot.objects.filter(
            status=Ballot.Status.OPEN, secret=True,
        ).count(),
    }
