"""Per-stage runner modules (A-F).

Each module exposes a ``get(...)`` function returning the Section-4 response
shape for a read, and (for long stages) a ``run(job)`` runner used by the job
queue. Runners read real cached artifacts or raise ``ComputeUnavailable`` — they
never synthesize pipeline outputs (handoff guardrail 1).
"""
