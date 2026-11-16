import json
import logging
import re
from typing import Any
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnableLambda

from app.schemas import SecurityAdvisoryInput, SecurityAdvisorySummary

logger = logging.getLogger("assist.security_pipeline")

SYSTEM_PROMPT = """너는 사이버 보안 및 취약점 분석 전문가다.
주어진 비정형 보안 공시(advisory)를 정밀 분석하여 정형화된 JSON 데이터로 추출하라.
비중국권 오픈 모델(Gemma 3, Hermes 3) 표준에 따라 다음 출력 형식을 엄격히 준수하라.

출력 형식 지침:
{format_instructions}
"""

HUMAN_PROMPT = """보안 공시 원문:
{raw_advisory}

출처 메타데이터:
{source}
"""

def _extract_json_substring(text: str) -> str:
    cleaned = text.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if match:
        return match.group(1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return cleaned[start : end + 1]
    return cleaned

def _rule_based_fallback(raw: str) -> SecurityAdvisorySummary:
    cve_match = re.search(r"(CVE-\d{4}-\d{4,7})", raw, re.IGNORECASE)
    cve_id = cve_match.group(1).upper() if cve_match else "UNKNOWN-CVE"
    
    severity = "MEDIUM"
    if re.search(r"\b(CRITICAL|치명|심각)\b", raw, re.IGNORECASE):
        severity = "CRITICAL"
    elif re.search(r"\b(HIGH|높음)\b", raw, re.IGNORECASE):
        severity = "HIGH"
    elif re.search(r"\b(LOW|낮음)\b", raw, re.IGNORECASE):
        severity = "LOW"

    cvss_match = re.search(r"(?:CVSS(?:\s*v[23])?(?:\s*score)?[:\s]*)(\d+(?:\.\d+)?)", raw, re.IGNORECASE)
    cvss_score = float(cvss_match.group(1)) if cvss_match else None

    cwe_ids = list(set(re.findall(r"(CWE-\d{1,5})", raw, re.IGNORECASE)))
    cwe_ids = [c.upper() for c in cwe_ids]

    return SecurityAdvisorySummary(
        cve_id=cve_id,
        severity=severity,
        cvss_score=cvss_score,
        cwe_ids=cwe_ids,
        affected_packages=[],
        summary_ko=f"{cve_id} 보안 권고 요약",
        action_guide_ko="취약점 영향 패키지를 최신 버전으로 업그레이드하고 접근 제어를 강화하세요."
    )

def build_security_advisory_chain(llm: Any = None):
    parser = PydanticOutputParser(pydantic_object=SecurityAdvisorySummary)
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", HUMAN_PROMPT),
    ]).partial(format_instructions=parser.get_format_instructions())

    def execute_chain(input_dict: dict[str, Any]) -> SecurityAdvisorySummary:
        raw = input_dict.get("raw_advisory", "")
        source = input_dict.get("source", "NVD/Advisory")
        
        if llm is None:
            return _rule_based_fallback(raw)

        try:
            formatted_prompt = prompt.format_prompt(raw_advisory=raw, source=source)
            response = llm.invoke(formatted_prompt)
            content = getattr(response, "content", response)
            if not isinstance(content, str):
                content = str(content)
            json_str = _extract_json_substring(content)
            return parser.parse(json_str)
        except Exception as e:
            logger.warning(f"Structured output parsing fallback due to: {e}")
            return _rule_based_fallback(raw)

    return RunnableLambda(execute_chain)

def synthesize_security_advisory(
    input_data: SecurityAdvisoryInput,
    llm: Any = None
) -> SecurityAdvisorySummary:
    chain = build_security_advisory_chain(llm=llm)
    result = chain.invoke({
        "raw_advisory": input_data.raw_advisory,
        "source": input_data.source or "Unknown"
    })
    logger.info(f"Security advisory synthesized: CVE={result.cve_id}, Severity={result.severity}")
    return result
