from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import BackgroundTasks, Depends, FastAPI, File, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from claimlens.container import Container
from claimlens.domain.models import ClaimStatus
from claimlens.errors import ClaimLensError, PayloadTooLarge
from claimlens.process import process_claim
from claimlens.security import configure_logging
from claimlens.services import AnswerView, ClaimService, ClaimView, Principal, QueueItem, to_view
from claimlens.settings import get_settings
from claimlens_api.deps import RateLimiter, get_container, get_service, limited
from claimlens_api.schemas import CreateClaim, DecisionRequest, ExplainRequest

log = logging.getLogger("claimlens.api")
general_limit = RateLimiter(limit=120)
explain_limit = RateLimiter(limit=20)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    app = FastAPI(
        title="ClaimLens API",
        version="0.1.0",
        description="Claim pre-check decision support. A human always decides.",
        docs_url="/docs" if settings.environment != "prod" else None,
        redoc_url=None,
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.max_upload_bytes + 64 * 1024:
            return JSONResponse({"detail": "request body too large"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(ClaimLensError)
    async def domain_error(_: Request, exc: ClaimLensError) -> JSONResponse:
        return JSONResponse({"detail": exc.public}, status_code=exc.status)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return JSONResponse({"detail": "internal error"}, status_code=500)  # never echo internals

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz(c: Container = Depends(get_container)) -> dict[str, object]:
        return {"status": "ok", "risk_model": c.models.risk.version if c.models.risk else None}

    @app.post("/v1/claims", response_model=ClaimView, status_code=201)
    def create_claim(
        body: CreateClaim,
        p: Principal = Depends(limited(general_limit, "g")),
        svc: ClaimService = Depends(get_service),
    ) -> ClaimView:
        return to_view(svc.create_claim(p, body.policy_id, body.consent_given), p.role)

    @app.get("/v1/claims", response_model=list[ClaimView])
    def list_claims(
        p: Principal = Depends(limited(general_limit, "g")),
        svc: ClaimService = Depends(get_service),
    ) -> list[ClaimView]:
        return svc.list_claims(p)

    @app.post("/v1/claims/{claim_id}/documents", status_code=201)
    async def upload(
        claim_id: str,
        file: UploadFile = File(...),
        p: Principal = Depends(limited(general_limit, "g")),
        svc: ClaimService = Depends(get_service),
        c: Container = Depends(get_container),
    ) -> dict[str, object]:
        data = await file.read(
            c.settings.max_upload_bytes + 1
        )  # bounded read: never buffer an unbounded body
        if len(data) > c.settings.max_upload_bytes:
            raise PayloadTooLarge("file is too large")
        ref = svc.add_document(
            p,
            claim_id,
            file.filename or "document",
            file.content_type or "application/octet-stream",
            data,
        )
        return {
            "document_id": ref.document_id,
            "filename": ref.filename,
            "size_bytes": ref.size_bytes,
        }

    @app.post("/v1/claims/{claim_id}/submit", response_model=ClaimView, status_code=202)
    def submit(
        claim_id: str,
        background: BackgroundTasks,
        p: Principal = Depends(limited(general_limit, "g")),
        svc: ClaimService = Depends(get_service),
        c: Container = Depends(get_container),
    ) -> ClaimView:
        claim = svc.submit(p, claim_id)
        if settings.inline_processing:  # laptop demo only: no separate worker needed
            background.add_task(process_claim, c, claim.tenant_id, claim.claim_id)
        return to_view(claim, p.role)

    @app.get("/v1/claims/{claim_id}", response_model=ClaimView)
    def get_claim(
        claim_id: str,
        p: Principal = Depends(limited(general_limit, "g")),
        svc: ClaimService = Depends(get_service),
    ) -> ClaimView:
        return svc.get_claim(p, claim_id)

    @app.post("/v1/claims/{claim_id}/explain", response_model=AnswerView)
    def explain(
        claim_id: str,
        body: ExplainRequest,
        p: Principal = Depends(limited(explain_limit, "x")),
        svc: ClaimService = Depends(get_service),
    ) -> AnswerView:
        return svc.explain(p, claim_id, body.question)

    @app.post("/v1/claims/{claim_id}/decision", response_model=ClaimView)
    def decide(
        claim_id: str,
        body: DecisionRequest,
        p: Principal = Depends(limited(general_limit, "g")),
        svc: ClaimService = Depends(get_service),
    ) -> ClaimView:
        return to_view(svc.decide(p, claim_id, body.decision, body.note), p.role)

    @app.delete("/v1/claims/{claim_id}", status_code=204)
    def delete_claim(
        claim_id: str,
        p: Principal = Depends(limited(general_limit, "g")),
        svc: ClaimService = Depends(get_service),
    ) -> Response:
        svc.delete_claim(p, claim_id)
        return Response(status_code=204)

    @app.get("/v1/reviewer/queue", response_model=list[QueueItem])
    def queue(
        p: Principal = Depends(limited(general_limit, "g")),
        svc: ClaimService = Depends(get_service),
    ) -> list[QueueItem]:
        return svc.reviewer_queue(p)

    _ = ClaimStatus  # re-exported for OpenAPI enums
    return app


app = create_app()
