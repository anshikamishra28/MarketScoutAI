"""FastAPI entry point for persistent market research runs."""
import json
import uuid
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agents.research_executor import _requirement_supported, execute_research
from database import store
from models.price_comparison import (
    PriceComparisonRequest,
    PriceComparisonResult,
    ProductIdentity,
    PriceOffer,
    RetailerResult,
)
from services.price_comparison import start_price_comparison, execute_price_comparison
from models.comparison import ComparisonRequest
from services.comparison_service import execute_comparison, start_generic_comparison
from tools.comparison_sources import ComparisonSourceAdapter

store.init_db()
app = FastAPI(title="MarketScoutAI API", description="Evidence-backed autonomous market research", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"], allow_methods=["*"], allow_headers=["*"])


class ResearchRequest(BaseModel):
    question: str = Field(min_length=8, max_length=2000)


def _run_research(run_id: str, question: str):
    execute_research(question, research_id=run_id)


def _run_price_comparison(comparison_id: str):
    execute_price_comparison(comparison_id)


def _generic_comparison_adapters() -> tuple[ComparisonSourceAdapter, ...]:
    """Registry boundary for generic sources; no adapters are enabled yet."""
    return ()


def _run_generic_comparison(comparison_id: str, request: ComparisonRequest):
    execute_comparison(
        request,
        adapters=_generic_comparison_adapters(),
        comparison_id=comparison_id,
    )


def _comparison_detail(record: dict) -> dict:
    """Build the public comparison payload with JSON-safe decimal prices."""
    result = PriceComparisonResult(
        comparison_id=record["comparison_id"],
        status=record["status"],
        products=[ProductIdentity(**product) for product in record["input_data"]["products"]],
        retailers=[RetailerResult(**check) for check in record["retailer_checks"]],
        offers=[PriceOffer(**{key: value for key, value in offer.items() if key != "id"}) for offer in record["offers"]],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
        error=record["error"],
    ).to_dict()
    result["request"] = record["input_data"]
    result["retailer_checks"] = result.pop("retailers")
    result["completed_at"] = record["completed_at"]
    return result


def _requirement_details(requirements: list[str], evidence: list[dict], question: str) -> list[dict]:
    """Serialize report-equivalent strict support mappings for the UI."""
    details = []
    for requirement in requirements:
        supporters = [item for item in evidence if _requirement_supported(item, requirement, question)]
        details.append({
            "requirement": requirement,
            "status": "Supported" if supporters else "UNRESOLVED / INSUFFICIENT EVIDENCE",
            "supporting_evidence_count": len(supporters),
            "supporting_evidence": [item.get("evidence_text") or item.get("claim", "") for item in supporters],
        })
    return details


@app.get("/")
def root():
    return {"message": "MarketScoutAI API is running", "docs": "/docs"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.post("/comparisons", status_code=202)
def start_generic_comparison_route(payload: ComparisonRequest, background_tasks: BackgroundTasks):
    try:
        record = start_generic_comparison(payload)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    comparison_id = record["comparison_id"]
    background_tasks.add_task(_run_generic_comparison, comparison_id, payload)
    return {
        "comparison_id": comparison_id,
        "status": "queued",
        "status_url": f"/comparisons/{comparison_id}/status",
    }


@app.get("/comparisons/{comparison_id}/status")
def get_generic_comparison_status(comparison_id: str):
    result = store.get_comparison_result(comparison_id)
    if result is None:
        raise HTTPException(404, "Comparison not found")
    errors = result.get("errors", [])
    return {
        "comparison_id": result["comparison_id"],
        "status": result["status"],
        "created_at": result["created_at"],
        "updated_at": result["updated_at"],
        "error": errors[0] if errors else None,
        "errors": errors,
    }


@app.get("/comparisons/{comparison_id}")
def get_generic_comparison(comparison_id: str):
    result = store.get_comparison_result(comparison_id)
    if result is None:
        raise HTTPException(404, "Comparison not found")
    return result


@app.post("/research", status_code=202)
def start_research(request: ResearchRequest, background_tasks: BackgroundTasks):
    run_id = str(uuid.uuid4())
    store.create_run(run_id, request.question.strip())
    background_tasks.add_task(_run_research, run_id, request.question.strip())
    return {"id": run_id, "status": "queued", "status_url": f"/research/{run_id}/status"}


@app.get("/research/{research_id}")
def get_research(research_id: str):
    run = store.get_run(research_id)
    if not run: raise HTTPException(404, "Research run not found")
    evidence = store.get_evidence(research_id)
    coverage = dict(run.get("coverage") or {})
    coverage["requirement_details"] = _requirement_details(run.get("plan", {}).get("information_needed", []), evidence, run.get("question", ""))
    return {**run, "coverage": coverage, "sources_count": len(store.get_sources(research_id)), "evidence": evidence, "report": store.get_report(research_id)}


@app.get("/research/{research_id}/status")
def get_status(research_id: str):
    run = store.get_run(research_id)
    if not run: raise HTTPException(404, "Research run not found")
    return {"id": run["id"], "status": run["status"], "iterations": run["iterations"], "updated_at": run["updated_at"], "activity": run["activity"], "error": run["error"]}


@app.get("/research/{research_id}/sources")
def get_sources(research_id: str):
    if not store.get_run(research_id): raise HTTPException(404, "Research run not found")
    sources = store.get_sources(research_id)
    for source in sources: source["evaluation"] = json.loads(source["evaluation"] or "{}")
    return {"sources": sources, "evidence": store.get_evidence(research_id)}


@app.get("/research/{research_id}/report")
def get_report(research_id: str):
    if not store.get_run(research_id): raise HTTPException(404, "Research run not found")
    report = store.get_report(research_id)
    if not report: raise HTTPException(404, "Report is not ready")
    return report


@app.post("/price-comparisons", status_code=202)
def start_comparison(payload: dict, background_tasks: BackgroundTasks):
    try:
        request = PriceComparisonRequest(**payload)
        record = start_price_comparison(request)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    comparison_id = record["comparison_id"]
    background_tasks.add_task(_run_price_comparison, comparison_id)
    return {
        "comparison_id": comparison_id,
        "status": record["status"],
        "status_url": f"/price-comparisons/{comparison_id}/status",
    }


@app.get("/price-comparisons/{comparison_id}/status")
def get_comparison_status(comparison_id: str):
    record = store.get_price_comparison(comparison_id, include_diagnostics=False)
    if not record:
        raise HTTPException(404, "Price comparison not found")
    return {
        "comparison_id": record["comparison_id"],
        "status": record["status"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "completed_at": record["completed_at"],
        "error": record["error"],
        "retailer_checks": record["retailer_checks"],
    }


@app.get("/price-comparisons/{comparison_id}")
def get_comparison(comparison_id: str):
    record = store.get_price_comparison(comparison_id)
    if not record:
        raise HTTPException(404, "Price comparison not found")
    return _comparison_detail(record)
