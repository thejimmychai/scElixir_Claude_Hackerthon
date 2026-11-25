# ==============================================================================
# Multi-Stage Reproducible Scientific Environment for scMagnify & scElixir
#   - Stage `core-cpu`: Portable CPU container (verified on Linux x86_64/arm64)
#   - Stage `gpu-cuda`: CUDA 12.4 container for high-throughput multi-seed sweeps
#                       and Google Cloud Run GPU Jobs / AI Studio cloud workers
#
# Uses mirror.gcr.io / nvcr.io official base images to prevent anonymous
# Docker Hub HTTP 429 rate-limiting on shared cloud / CI runners.
#
# Build CPU image:
#   docker build --target core-cpu -t scmagnify-scelixir:1.0 -f docker/Dockerfile .
#
# Build GPU image:
#   docker build --target gpu-cuda -t scmagnify-scelixir:1.0-gpu -f docker/Dockerfile .
# ==============================================================================

FROM mirror.gcr.io/library/python:3.11-slim-bookworm AS core-cpu

LABEL org.opencontainers.image.title="scMagnify + scElixir Multi-Scale Multiomic GRN & Reprogramming"
LABEL org.opencontainers.image.description="Reproducible environment for scMagnify (MSNGC, RegDecomp, MOODS, SEACells), SCENIC+ comparison, scElixir developmental lung reprogramming, and Google AI Studio / Gemini Interactions API cloud orchestration."
LABEL org.opencontainers.image.version="1.0.0"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    OMP_NUM_THREADS=2 \
    OPENBLAS_NUM_THREADS=2 \
    MKL_NUM_THREADS=2 \
    NUMBA_CACHE_DIR=/tmp/numba_cache \
    MPLCONFIGDIR=/tmp/matplotlib_cache \
    SCMAGNIFY_DATA=/opt/scmagnify_cache

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    git \
    curl \
    ca-certificates \
    zlib1g-dev \
    libbz2-dev \
    liblzma-dev \
    libcurl4-openssl-dev \
    libssl-dev \
    libhdf5-dev \
    libxml2-dev \
    libgl1 \
    libglib2.0-0 \
    fontconfig \
    fonts-dejavu-core \
    samtools \
    tabix \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.6.14

WORKDIR /workspace

COPY docker/requirements.scmagnify.txt /workspace/docker/requirements.scmagnify.txt

# Install CPU PyTorch first so uv resolves lightweight CPU wheels, then scientific stack
RUN uv venv /opt/scm_env --python 3.11 \
    && uv pip install --python /opt/scm_env/bin/python --no-cache \
       --index-url https://download.pytorch.org/whl/cpu \
       torch==2.5.1+cpu \
    && uv pip install --python /opt/scm_env/bin/python --no-cache \
       -r /workspace/docker/requirements.scmagnify.txt

ENV PATH="/opt/scm_env/bin:${PATH}" \
    PYTHONPATH="/workspace"

# Copy stabilized scMagnify source and install package
COPY pyproject.toml README.md LICENSE /workspace/
COPY src /workspace/src
RUN uv pip install --python /opt/scm_env/bin/python --no-cache --no-deps -e /workspace

COPY cloud_gemini /workspace/cloud_gemini
COPY reproduce/*.py /workspace/reproduce/
COPY scelixir_lung/*.py /workspace/scelixir_lung/
COPY tests /workspace/tests
COPY docker/verify_scmagnify_env.py /workspace/docker/verify_scmagnify_env.py
RUN mkdir -p /opt/scmagnify_cache /tmp/numba_cache /tmp/matplotlib_cache \
    && python /workspace/docker/verify_scmagnify_env.py --quick \
    && rm -rf /tmp/numba_cache/* \
    && chmod -R 0777 /opt/scmagnify_cache /tmp/numba_cache /tmp/matplotlib_cache /workspace

ENTRYPOINT ["python"]
CMD ["/workspace/docker/verify_scmagnify_env.py"]

# ==============================================================================
# GPU CUDA 12.4 Stage for Cloud Run GPU / Workstation Multi-Seed Execution
# ==============================================================================
FROM nvcr.io/nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 AS gpu-cuda

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    NUMBA_CACHE_DIR=/tmp/numba_cache \
    MPLCONFIGDIR=/tmp/matplotlib_cache \
    SCMAGNIFY_DATA=/opt/scmagnify_cache

RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    build-essential \
    gcc \
    g++ \
    git \
    curl \
    ca-certificates \
    zlib1g-dev \
    libbz2-dev \
    liblzma-dev \
    libcurl4-openssl-dev \
    libssl-dev \
    libhdf5-dev \
    libxml2-dev \
    libgl1 \
    libglib2.0-0 \
    fontconfig \
    fonts-dejavu-core \
    samtools \
    tabix \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir uv==0.6.14

WORKDIR /workspace
COPY docker/requirements.scmagnify.txt /workspace/docker/requirements.scmagnify.txt

RUN uv python install 3.11 \
    && uv venv /opt/scm_env --python 3.11 \
    && uv pip install --python /opt/scm_env/bin/python --no-cache \
       --index-url https://download.pytorch.org/whl/cu124 \
       torch==2.5.1 \
    && uv pip install --python /opt/scm_env/bin/python --no-cache \
       -r /workspace/docker/requirements.scmagnify.txt

ENV PATH="/opt/scm_env/bin:${PATH}" \
    PYTHONPATH="/workspace"

COPY pyproject.toml README.md LICENSE /workspace/
COPY src /workspace/src
RUN uv pip install --python /opt/scm_env/bin/python --no-cache --no-deps -e /workspace

COPY cloud_gemini /workspace/cloud_gemini
COPY reproduce/*.py /workspace/reproduce/
COPY scelixir_lung/*.py /workspace/scelixir_lung/
COPY tests /workspace/tests
COPY docker/verify_scmagnify_env.py /workspace/docker/verify_scmagnify_env.py
RUN mkdir -p /opt/scmagnify_cache /tmp/numba_cache /tmp/matplotlib_cache \
    && python /workspace/docker/verify_scmagnify_env.py --quick \
    && rm -rf /tmp/numba_cache/* \
    && chmod -R 0777 /opt/scmagnify_cache /tmp/numba_cache /tmp/matplotlib_cache /workspace

ENTRYPOINT ["python"]
CMD ["/workspace/docker/verify_scmagnify_env.py"]
