import pytest
from app.schemas import SecurityAdvisoryInput, SecurityAdvisorySummary
from app.security_pipeline import build_security_advisory_chain, synthesize_security_advisory
from fastapi.testclient import TestClient
from app.main import app

def test_security_advisory_summary_schema():
    data = {
        "cve_id": "CVE-2026-1234",
        "severity": "HIGH",
        "cvss_score": 8.5,
        "cwe_ids": ["CWE-79", "CWE-116"],
        "affected_packages": ["flask<3.0.0"],
        "summary_ko": "Flask 템플릿 렌더링 시 XSS 취약점 발생",
        "action_guide_ko": "Flask 패키지를 3.0.0 이상으로 즉시 업그레이드하고 입력을 이스케이프하세요."
    }
    obj = SecurityAdvisorySummary(**data)
    assert obj.cve_id == "CVE-2026-1234"
    assert obj.severity == "HIGH"
    assert obj.cvss_score == 8.5
    assert "CWE-79" in obj.cwe_ids
    assert obj.action_guide_ko.startswith("Flask")

def test_security_advisory_pipeline_with_mock_llm():
    raw_text = """
    A critical vulnerability CVE-2026-9999 has been discovered in package 'express-jwt' before 8.1.0.
    Improper validation allows authentication bypass (CWE-287). CVSS score is 9.8 (CRITICAL).
    Remediation: Upgrade express-jwt to 8.1.0 or higher immediately.
    """
    input_data = SecurityAdvisoryInput(raw_advisory=raw_text)
    
    class MockLLM:
        def invoke(self, prompt_value):
            return """{
                "cve_id": "CVE-2026-9999",
                "severity": "CRITICAL",
                "cvss_score": 9.8,
                "cwe_ids": ["CWE-287"],
                "affected_packages": ["express-jwt<8.1.0"],
                "summary_ko": "express-jwt 인증 우회 취약점",
                "action_guide_ko": "express-jwt를 8.1.0 이상으로 업그레이드하세요."
            }"""

    summary = synthesize_security_advisory(input_data, llm=MockLLM())
    assert summary.cve_id == "CVE-2026-9999"
    assert summary.severity == "CRITICAL"
    assert summary.cvss_score == 9.8
    assert "CWE-287" in summary.cwe_ids
    assert "8.1.0" in summary.action_guide_ko

def test_api_security_synthesize_endpoint():
    client = TestClient(app)
    response = client.post("/v1/security/synthesize", json={
        "raw_advisory": "CVE-2026-5555: Buffer overflow in OpenSSL (CWE-119, CVSS 7.5 HIGH). Upgrade to 3.0.12.",
        "source": "NVD"
    })
    assert response.status_code == 200
    data = response.json()
    assert "cve_id" in data
    assert "severity" in data
    assert "action_guide_ko" in data
