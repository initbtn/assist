from fastapi import APIRouter
from app.schemas import SecurityAdvisoryInput, SecurityAdvisorySummary
from app.security_pipeline import synthesize_security_advisory

router = APIRouter(prefix="/v1/security", tags=["security"])

@router.post("/synthesize", response_model=SecurityAdvisorySummary)
def synthesize_advisory(payload: SecurityAdvisoryInput) -> SecurityAdvisorySummary:
    return synthesize_security_advisory(payload)
