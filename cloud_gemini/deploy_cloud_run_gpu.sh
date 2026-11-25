#!/usr/bin/env bash
# ==============================================================================
# One-Command Cloud Deployment for Large scMagnify + scElixir GPU Jobs
# Compatible with Google AI Studio exported Cloud projects & Gemini API keys.
# ==============================================================================
set -euo pipefail

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-your-gcp-project-id}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/scelixir/scmagnify-scelixir:1.0-gpu"
JOB_NAME="${JOB_NAME:-scmagnify-scelixir-lung-10seed}"

echo "[1/4] Building CUDA 12.4 GPU Docker image (${IMAGE_URI})..."
docker build --target gpu-cuda -t "${IMAGE_URI}" -f docker/Dockerfile .

echo "[2/4] Pushing container to Artifact Registry..."
docker push "${IMAGE_URI}"

echo "[3/4] Generating Cloud Run GPU Job manifest wired to GEMINI_API_KEY..."
python3 -m cloud_gemini.gemini_interactions_runner --mode cloud-run-manifest --output-dir ./cloud_out
sed -i.bak "s|scmagnify-scelixir:1.0-gpu|${IMAGE_URI}|g" ./cloud_out/cloud_run_gpu_job.json

echo "[4/4] Deploying & executing Cloud Run GPU Job (${JOB_NAME}) in ${REGION}..."
gcloud run jobs replace ./cloud_out/cloud_run_gpu_job.json --project="${PROJECT_ID}" --region="${REGION}"
gcloud run jobs execute "${JOB_NAME}" --project="${PROJECT_ID}" --region="${REGION}" --async

echo "[DONE] Cloud Run GPU Job launched! Post-training Gemini Interactions API audit will write to GCS."
