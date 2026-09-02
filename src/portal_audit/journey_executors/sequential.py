"""The V1 supervised linear Journey execution strategy."""

from __future__ import annotations


class SequentialJourneyExecutor:
    """Delegate the established sequential workflow to the audit runner.

    The small strategy boundary is deliberate: future executors can implement
    conditional or approval-driven traversal without changing the runner's
    public API or the CheckSpec execution pipeline.
    """

    async def execute(self, runner, request):
        return await runner._run_sequential(request)
