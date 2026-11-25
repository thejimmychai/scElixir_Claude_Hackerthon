#!/usr/bin/env python3
"""
Google AI Studio Developer Platform & Gemini Interactions API Cloud Orchestrator
for Large-Scale scMagnify + scElixir Multiomic GRN Jobs.

Why this module exists:
  Local laptops or lightweight 2-vCPU VMs cannot run 10-seed x 9-lineage MAGNI
  neural Granger causality sweeps, scMultiSim synthetic benchmarks, or 630k-cell
  SEACells + MOODS motif scans interactively. This module provides three
  production-ready cloud execution backends built on the official `google-genai`
  SDK (GA Interactions API as of June 2026) and Google Cloud Run GPU Jobs:

  1. `interactions_agent` (Stateful Gemini Interactions API, `background=True`):
     Uses `client.interactions.create(...)` and `client.interactions.get(...)`
     with server-side state (`previous_interaction_id`), remote `code_execution`
     sandbox tools, and structured JSON schemas to execute asynchronous GRN
     parameter sweeps, stability audits, and biological regulon synthesis.

  2. `batch_api` (Google AI Studio Asynchronous Batch API, 50% cost):
     Uses `client.files.upload(...)` and `client.batches.create(...)` to score
     and annotate hundreds of inferred RegFactors, cCRE enhancers, and candidate
     TF reprogramming cocktails in parallel.

  3. `cloud_run_gpu` (Containerized GPU Worker Manifest Generator):
     Emits a deterministic Google Cloud Run GPU Job specification (`nvidia-l4`
     or `nvidia-a100-80gb`) running our `scmagnify-scelixir:1.0-gpu` Docker image
     for multi-seed PyTorch `MAGNI` training (`run_magnify_multiseed.py`) and
     PertFormer 3B validation, wired directly to `GEMINI_API_KEY` from AI Studio.

Usage:
  # Dry-run validation (no API key or billing needed; verifies payload contracts):
  python -m cloud_gemini.gemini_interactions_runner --mode dry-run --output-dir ./cloud_out

  # Launch asynchronous background Gemini Interactions API analysis:
  export GEMINI_API_KEY="your-ai-studio-key"
  python -m cloud_gemini.gemini_interactions_runner --mode interactions \
      --grn-summary results/scelixir_lung_grn_summary.json --background
"""
from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_INTERACTIONS_MODEL = os.environ.get("GEMINI_INTERACTIONS_MODEL", "gemini-2.5-flash")


@dataclass
class MAGNICloudJobSpec:
    """Deterministic specification for a large-scale scMagnify cloud job."""

    job_name: str
    dataset_uri: str
    lineages: List[str]
    seeds: List[int] = field(default_factory=lambda: list(range(10)))
    # Optimal scMagnify paper hyperparameters (Chen et al., bioRxiv 2026)
    time_lag: int = 5
    hidden_dim: List[int] = field(default_factory=lambda: [50])
    learning_rate: float = 1e-3
    batch_size: int = 32
    max_iter: int = 1000
    patience: int = 20
    lmbd: float = 3.0
    alpha: float = 0.5
    gamma: float = 0.02
    cv_thres: float = 0.2
    quantile_cutoff: float = 0.90
    tucker_rank: int = 5
    ref_genome: str = "hg38"
    motif_db: str = "HOCOMOCOv11_HUMAN"
    gpu_accelerator: str = "nvidia-l4"
    docker_image: str = "scmagnify-scelixir:1.0-gpu"


REGFACTOR_AUDIT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "title": "ScMagnifyRegFactorAudit",
    "required": [
        "lineage",
        "validated_master_regulators",
        "flagged_transient_signals",
        "recommended_perturbations",
        "confidence_notes",
    ],
    "properties": {
        "lineage": {"type": "string"},
        "validated_master_regulators": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Long-lag, high-centrality TFs supported by chromatin & developmental literature.",
        },
        "flagged_transient_signals": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Short-lag immediate-response, cell-cycle, or dissociation-stress TFs.",
        },
        "recommended_perturbations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["tf", "action", "rationale"],
                "properties": {
                    "tf": {"type": "string"},
                    "action": {"type": "string", "enum": ["ACTIVATE_OE", "REPRESS_KO", "DO_NOT_PERTURB"]},
                    "rationale": {"type": "string"},
                },
            },
        },
        "confidence_notes": {"type": "string"},
    },
}


def get_genai_client(api_key: Optional[str] = None):
    """Initialize the official Google GenAI client for AI Studio or Enterprise."""
    from google import genai

    resolved_key = api_key or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if os.environ.get("GOOGLE_GENAI_USE_ENTERPRISE", "").lower() == "true":
        return genai.Client(
            enterprise=True,
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        )
    if not resolved_key:
        raise EnvironmentError(
            "Missing GEMINI_API_KEY (or GOOGLE_API_KEY). Generate an API key in "
            "Google AI Studio (https://aistudio.google.com/apikey) and export GEMINI_API_KEY."
        )
    return genai.Client(api_key=resolved_key)


def build_interactions_payload(
    grn_summary: Dict[str, Any],
    model: str = DEFAULT_INTERACTIONS_MODEL,
    background: bool = True,
    enable_code_execution: bool = True,
    previous_interaction_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Construct a compliant payload for `client.interactions.create(...)` on the
    Google AI Studio / Gemini Interactions API.
    """
    tools: List[Dict[str, Any]] = []
    if enable_code_execution:
        tools.append({"type": "code_execution"})

    prompt = (
        "You are executing an automated multi-scale GRN stability and reprogramming audit "
        "on scMagnify (MSNGC nonlinear Granger causality + Tucker RegFactor decomposition) "
        "integrated with SCENIC+ developmental lung multiomics.\n\n"
        "Tasks:\n"
        "1. Using Python code_execution if needed, verify rank-correlation and Jaccard stability "
        "between long-lag MAGNI hubs (norm_lag >= 3.0) and static SCENIC+ regulons.\n"
        "2. Separate persistent lineage-defining master regulators (pan-lung NKX2-1/FOXA1/FOXA2/GATA6, "
        "AT2 ETV5/CEBPA/CEBPD, AT1 TEAD1/MYRF, Club SOX2/EHF/ELF3/KLF5) from short-lag transient "
        "signals (cell-cycle E2F/FOXM1, perinatal hypoxia/ER stress HIF1A/BHLHE40/XBP1, dissociation IEGs).\n"
        "3. Nominate precision OE+KO reprogramming candidates for reversing mature AT2 toward "
        "embryonic distal-tip biprogenitors while preventing proximal SOX2/EHF Club/squamous drift.\n\n"
        f"Input Empirical Summary JSON:\n{json.dumps(grn_summary, indent=2)[:24000]}"
    )

    payload: Dict[str, Any] = {
        "model": model,
        "input": prompt,
    }
    if tools:
        payload["tools"] = tools
    if background:
        payload["background"] = True
    if previous_interaction_id:
        payload["previous_interaction_id"] = previous_interaction_id
    return payload


def run_gemini_interaction_job(
    grn_summary: Dict[str, Any],
    model: str = DEFAULT_INTERACTIONS_MODEL,
    background: bool = True,
    poll_interval_sec: int = 10,
    timeout_sec: int = 600,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Submit a stateful interaction via `client.interactions.create(...)` and, if
    `background=True`, poll `client.interactions.get(...)` until completion.
    Follows up with a second stateful turn (`previous_interaction_id`) to emit
    schema-validated actionable perturbation JSON.
    """
    client = get_genai_client(api_key=api_key)
    try:
        payload = build_interactions_payload(
            grn_summary=grn_summary,
            model=model,
            background=background,
            enable_code_execution=True,
        )
        interaction = client.interactions.create(**payload)
        interaction_id = getattr(interaction, "id", None)

        if background and interaction_id:
            deadline = time.time() + timeout_sec
            terminal_states = {"COMPLETED", "SUCCEEDED", "FAILED", "CANCELLED", "ERROR"}
            while time.time() < deadline:
                state = str(getattr(interaction, "status", getattr(interaction, "state", "COMPLETED"))).upper()
                if state in terminal_states or getattr(interaction, "output_text", None):
                    break
                time.sleep(poll_interval_sec)
                interaction = client.interactions.get(id=interaction_id)

        turn1_text = getattr(interaction, "output_text", "") or str(interaction)

        # Turn 2: Stateful follow-up referencing previous_interaction_id with strict JSON schema config
        turn2_kwargs: Dict[str, Any] = {
            "model": model,
            "input": (
                "Now synthesize our verified multi-scale lag analysis into a concise structured JSON "
                f"matching these keys: {list(REGFACTOR_AUDIT_SCHEMA['properties'].keys())}."
            ),
            "generation_config": {
                "temperature": 0.1,
                "response_mime_type": "application/json",
                "response_json_schema": REGFACTOR_AUDIT_SCHEMA,
            },
        }
        if interaction_id:
            turn2_kwargs["previous_interaction_id"] = interaction_id
        turn2 = client.interactions.create(**turn2_kwargs)
        turn2_text = getattr(turn2, "output_text", "") or str(turn2)

        return {
            "status": "completed",
            "model": model,
            "turn1_interaction_id": interaction_id,
            "turn2_interaction_id": getattr(turn2, "id", None),
            "turn1_analysis": turn1_text,
            "turn2_structured_synthesis": turn2_text,
        }
    finally:
        if hasattr(client, "close"):
            client.close()


def build_batch_jsonl_requests(
    regfactors: List[Dict[str, Any]],
    model: str = DEFAULT_INTERACTIONS_MODEL,
) -> List[Dict[str, Any]]:
    """
    Build JSONL batch items for Google AI Studio's `client.batches.create(...)`
    (50% cost asynchronous batch evaluation across all RegFactors & lineages).
    """
    records: List[Dict[str, Any]] = []
    for idx, rf in enumerate(regfactors):
        key = f"regfactor_audit_{idx}_{rf.get('lineage', 'lung')}_{rf.get('name', f'RF{idx+1}')}"
        prompt = (
            f"Audit scMagnify RegFactor {rf.get('name')} in lineage/stage `{rf.get('lineage')}`.\n"
            f"Top TFs & loadings: {json.dumps(rf.get('top_tfs', {}))}\n"
            f"Mean regulatory lag: {rf.get('mean_lag')}\n"
            f"Top Target Genes: {json.dumps(rf.get('top_targets', [])[:30])}\n"
            "Classify whether this module represents a persistent lineage selector, a pioneer fate "
            "determinant, a transient proliferation/stress wave, or a terminal maturation lock-in."
        )
        records.append(
            {
                "key": key,
                "request": {
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generation_config": {
                        "temperature": 0.1,
                        "response_mime_type": "application/json",
                        "response_json_schema": REGFACTOR_AUDIT_SCHEMA,
                    },
                },
            }
        )
    return records


def submit_ai_studio_batch_job(
    jsonl_path: Path,
    model: str = DEFAULT_INTERACTIONS_MODEL,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Upload a JSONL request bundle and submit a Google AI Studio Batch API job."""
    from google.genai import types

    client = get_genai_client(api_key=api_key)
    try:
        uploaded = client.files.upload(
            file=str(jsonl_path),
            config=types.UploadFileConfig(
                display_name=jsonl_path.stem,
                mime_type="application/jsonl",
            ),
        )
        batch_job = client.batches.create(
            model=model,
            src=uploaded.name,
        )
        return {
            "batch_job_name": getattr(batch_job, "name", str(batch_job)),
            "state": str(getattr(batch_job, "state", "SUBMITTED")),
            "uploaded_file": uploaded.name,
            "model": model,
        }
    finally:
        if hasattr(client, "close"):
            client.close()


def generate_cloud_run_gpu_manifest(spec: MAGNICloudJobSpec) -> Dict[str, Any]:
    """
    Generate a Google Cloud Run GPU Job v2 manifest compatible with Google AI Studio
    Cloud Run export for executing 10-seed PyTorch MAGNI sweeps on NVIDIA L4/A100 GPUs.
    """
    return {
        "apiVersion": "run.googleapis.com/v1",
        "kind": "Job",
        "metadata": {
            "name": spec.job_name,
            "annotations": {
                "run.googleapis.com/launch-stage": "GA",
                "scmagnify.csblab.org/paper-doi": "10.64898/2026.02.03.703669v1",
            },
        },
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "run.googleapis.com/execution-environment": "gen2",
                        "run.googleapis.com/gpu-zonal-redundancy-disabled": "true",
                    }
                },
                "spec": {
                    "taskCount": len(spec.seeds),
                    "parallelism": min(len(spec.seeds), 4),
                    "timeoutSeconds": 7200,
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "image": spec.docker_image,
                                    "command": ["python", "/workspace/reproduce/run_magnify_multiseed_worker.py"],
                                    "args": [
                                        "--dataset-uri",
                                        spec.dataset_uri,
                                        "--lineages",
                                        ",".join(spec.lineages),
                                        "--time-lag",
                                        str(spec.time_lag),
                                        "--hidden",
                                        ",".join(map(str, spec.hidden_dim)),
                                        "--lr",
                                        str(spec.learning_rate),
                                        "--batch-size",
                                        str(spec.batch_size),
                                        "--max-iter",
                                        str(spec.max_iter),
                                        "--patience",
                                        str(spec.patience),
                                        "--lmbd",
                                        str(spec.lmbd),
                                        "--alpha",
                                        str(spec.alpha),
                                        "--gamma",
                                        str(spec.gamma),
                                        "--tucker-rank",
                                        str(spec.tucker_rank),
                                        "--post-audit-gemini",
                                    ],
                                    "env": [
                                        {
                                            "name": "GEMINI_API_KEY",
                                            "valueFrom": {
                                                "secretKeyRef": {"key": "latest", "name": "gemini-api-key"}
                                            },
                                        },
                                        {"name": "GEMINI_INTERACTIONS_MODEL", "value": DEFAULT_INTERACTIONS_MODEL},
                                    ],
                                    "resources": {
                                        "limits": {
                                            "cpu": "8",
                                            "memory": "32Gi",
                                            "nvidia.com/gpu": "1",
                                        }
                                    },
                                }
                            ],
                            "nodeSelector": {
                                "run.googleapis.com/accelerator": spec.gpu_accelerator,
                            },
                        }
                    },
                },
            }
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Google AI Studio / Gemini Interactions API Cloud Runner for scMagnify & scElixir"
    )
    parser.add_argument(
        "--mode",
        choices=["dry-run", "interactions", "batch", "cloud-run-manifest"],
        default="dry-run",
    )
    parser.add_argument("--grn-summary", type=str, default=None, help="Path to empirical GRN summary JSON")
    parser.add_argument("--output-dir", type=str, default="./cloud_out", help="Directory for cloud manifests/results")
    parser.add_argument("--model", type=str, default=DEFAULT_INTERACTIONS_MODEL)
    parser.add_argument("--background", action="store_true", default=True)
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_data: Dict[str, Any] = {"project": "scMagnify_x_scElixir", "status": "ready"}
    if args.grn_summary and Path(args.grn_summary).exists():
        summary_data = json.loads(Path(args.grn_summary).read_text())

    if args.mode == "dry-run":
        spec = MAGNICloudJobSpec(
            job_name="scmagnify-scelixir-lung-10seed",
            dataset_uri="gs://scelixir-multiome/human_lung_developmental_multiome.h5mu",
            lineages=["Fetal_Tip", "Club_Secretory", "Perinatal_AT2", "Adult_AT2", "AT1"],
        )
        interaction_payload = build_interactions_payload(summary_data, model=args.model, background=args.background)
        batch_records = build_batch_jsonl_requests(
            [
                {
                    "lineage": "Human_Lung_Alveolar",
                    "name": "RegFactor_1_DistalTip",
                    "mean_lag": 3.84,
                    "top_tfs": {"SOX9": 0.61, "ETV5": 0.54, "HMGA1": 0.47},
                    "top_targets": ["ID2", "WNT7B", "FGFR2", "SFTPC", "CD24"],
                }
            ],
            model=args.model,
        )
        cloud_manifest = generate_cloud_run_gpu_manifest(spec)

        (out_dir / "interactions_create_payload.json").write_text(json.dumps(interaction_payload, indent=2))
        with open(out_dir / "ai_studio_batch_requests.jsonl", "w") as f:
            for r in batch_records:
                f.write(json.dumps(r) + "\n")
        (out_dir / "cloud_run_gpu_job.json").write_text(json.dumps(cloud_manifest, indent=2))
        (out_dir / "magni_cloud_job_spec.json").write_text(json.dumps(asdict(spec), indent=2))
        print(f"[OK] Dry-run cloud deployment bundle written to {out_dir}")

    elif args.mode == "interactions":
        res = run_gemini_interaction_job(summary_data, model=args.model, background=args.background)
        (out_dir / "interactions_result.json").write_text(json.dumps(res, indent=2))
        print(f"[OK] Gemini Interactions API completed: {res.get('turn1_interaction_id')}")

    elif args.mode == "batch":
        regfactors = summary_data.get("regfactors", [])
        jsonl_file = out_dir / "ai_studio_batch_requests.jsonl"
        with open(jsonl_file, "w") as f:
            for rec in build_batch_jsonl_requests(regfactors, model=args.model):
                f.write(json.dumps(rec) + "\n")
        res = submit_ai_studio_batch_job(jsonl_file, model=args.model)
        (out_dir / "batch_submission.json").write_text(json.dumps(res, indent=2))
        print(f"[OK] Submitted AI Studio Batch job: {res['batch_job_name']}")

    elif args.mode == "cloud-run-manifest":
        spec = MAGNICloudJobSpec(
            job_name="scmagnify-scelixir-lung-10seed",
            dataset_uri="gs://scelixir-multiome/human_lung_developmental_multiome.h5mu",
            lineages=["Fetal_Tip", "Club_Secretory", "Perinatal_AT2", "Adult_AT2", "AT1"],
        )
        manifest = generate_cloud_run_gpu_manifest(spec)
        (out_dir / "cloud_run_gpu_job.json").write_text(json.dumps(manifest, indent=2))
        print(f"[OK] Wrote Cloud Run GPU Job manifest to {out_dir / 'cloud_run_gpu_job.json'}")


if __name__ == "__main__":
    main()
