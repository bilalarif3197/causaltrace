"""CausalTrace API.

Research prototype. Not a medical device and not a clinical decision tool.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from schemas.models import AnalysisResult, AnalyzeRequest, ExampleCase  # noqa: E402
from services import cases  # noqa: E402
from services.llm_client import MockUnavailable, build_client  # noqa: E402
from services.pipeline import run_analysis  # noqa: E402

DISCLAIMER = (
    "CausalTrace is a research prototype for structured causality assessment. It does not "
    "establish medical causation, is not a medical device, and is not a clinical decision tool."
)

app = FastAPI(title="CausalTrace API", version="0.1.0", description=DISCLAIMER)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",") if o],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_client = build_client()


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "mode": _client.mode,
        "model": _client.name,
        "disclaimer": DISCLAIMER,
        "mock_cases": getattr(_client, "available_cases", list)(),
        # Which structured-output mode the provider actually accepted. None
        # until the first live call negotiates it.
        "json_mode": getattr(_client, "active_json_mode", None),
        "notes": getattr(_client, "notes", []),
    }


@app.get("/api/examples", response_model=list[ExampleCase])
def examples() -> list[ExampleCase]:
    return cases.EXAMPLE_CASES


@app.post("/api/analyze", response_model=AnalysisResult)
def analyze(req: AnalyzeRequest) -> AnalysisResult:
    try:
        return run_analysis(_client, req)
    except MockUnavailable as exc:
        # 422, not 500: the request is valid, the server just has no recorded
        # analysis for it and no API key to produce one.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
