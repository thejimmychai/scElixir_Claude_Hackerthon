"""Universal Developmental Reprogramming Pipeline — backend package.

A zero-dependency (Python standard library only) implementation of the
6-stage pipeline API described in ``docs/CLAUDE_CODE_HANDOFF.md`` (Section 4).

The suggested framework in the handoff is FastAPI; this implementation uses
``http.server`` instead so the app boots on any machine with a Python 3.8+
interpreter and no ``pip install`` step — important because the pipeline's real
compute (scVI, CellOracle, PertFormer) lives on separate GPU hosts and the
reference bundle is meant to run anywhere. The request/response *shapes* are the
contract, and they match Section 4 exactly.
"""

__all__ = ["config", "data_loader", "registry", "artifacts", "capabilities", "organ_bundles", "jobs", "app"]
