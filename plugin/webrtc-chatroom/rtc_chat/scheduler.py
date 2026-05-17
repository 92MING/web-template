from .candidate import SchedulerCandidate, SchedulerCreationParamData


class DefaultScheduler(SchedulerCandidate, key="default"):
    """Default scheduler placeholder."""

    @classmethod
    def Create(cls, param: SchedulerCreationParamData, room) -> "DefaultScheduler":
        return cls(room=room)


__all__ = ["DefaultScheduler"]
