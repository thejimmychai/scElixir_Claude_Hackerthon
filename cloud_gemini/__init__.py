"""Cloud deployment & Gemini Interactions API orchestration for scMagnify + scElixir."""
from .gemini_interactions_runner import (
    MAGNICloudJobSpec,
    REGFACTOR_AUDIT_SCHEMA,
    build_batch_jsonl_requests,
    build_interactions_payload,
    generate_cloud_run_gpu_manifest,
    get_genai_client,
    run_gemini_interaction_job,
    submit_ai_studio_batch_job,
)

__all__ = [
    "MAGNICloudJobSpec",
    "REGFACTOR_AUDIT_SCHEMA",
    "build_batch_jsonl_requests",
    "build_interactions_payload",
    "generate_cloud_run_gpu_manifest",
    "get_genai_client",
    "run_gemini_interaction_job",
    "submit_ai_studio_batch_job",
]
