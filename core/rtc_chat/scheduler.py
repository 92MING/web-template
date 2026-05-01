'''默认的scheduler实现.'''

from .candidate import SchedulerCandidate, SchedulerCreationParamData


class DefaultScheduler(SchedulerCandidate, key="default"):
    '''最简单的默认scheduler，仅作为占位存在，不参与房间逻辑调度。'''

    @classmethod
    def Create(cls, param: SchedulerCreationParamData, room) -> "DefaultScheduler":
        return cls(room=room)


__all__ = ["DefaultScheduler"]
