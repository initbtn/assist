import pytest
from app.collectors import (
    CweRecordItem,
    CapecRecordItem,
    CveRecordItem,
    parse_cwe_sample,
    parse_capec_sample,
    parse_nvd_cve_item,
)

SAMPLE_CWE_DICT = {
    "ID": "79",
    "Name": "Improper Neutralization of Input During Web Page Generation ('Cross-site Scripting')",
    "Abstraction": "Class",
    "Structure": "Simple",
    "Status": "Stable",
    "Description": "The software does not neutralize or incorrectly neutralizes user-controllable input before it is placed in output that is used as a web page.",
    "Likelihood_Of_Exploit": "High",
    "Mitigations": [
        {"Phase": "Implementation", "Description": "Use contextual output encoding"}
    ],
}

SAMPLE_CAPEC_DICT = {
    "ID": "66",
    "Name": "SQL Injection",
    "Abstraction": "Standard",
    "Status": "Stable",
    "Summary": "An adversary exploits insecure SQL queries by injecting malicious SQL statements.",
    "Severity": "Very High",
    "Likelihood": "High",
    "Related_Weaknesses": ["89", "564"],
    "Mitigations": [
        "Use parameterized queries or ORM frameworks"
    ],
}

SAMPLE_NVD_CVE_DICT = {
    "cve": {
        "id": "CVE-2026-9999",
        "published": "2026-11-12T00:00:00.000Z",
        "lastModified": "2026-11-12T01:00:00.000Z",
        "descriptions": [
            {"lang": "en", "value": "A critical command injection vulnerability in example-lib enables remote code execution."}
        ],
        "metrics": {
            "cvssMetricV31": [
                {
                    "cvssData": {
                        "baseScore": 9.8,
                        "baseSeverity": "CRITICAL"
                    }
                }
            ]
        },
        "weaknesses": [
            {
                "description": [{"lang": "en", "value": "CWE-78"}]
            }
        ],
        "configurations": [
            {
                "nodes": [
                    {
                        "cpeMatch": [
                            {"criteria": "cpe:2.3:a:example:example-lib:*:*:*:*:*:*:*:*", "versionEndExcluding": "2.4.0"}
                        ]
                    }
                ]
            }
        ]
    }
}


def test_parse_cwe_sample():
    item = parse_cwe_sample(SAMPLE_CWE_DICT)
    assert item.cwe_id == "CWE-79"
    assert "Cross-site Scripting" in item.name
    assert item.likelihood_of_exploit == "High"
    assert len(item.mitigations) == 1


def test_parse_capec_sample():
    item = parse_capec_sample(SAMPLE_CAPEC_DICT)
    assert item.capec_id == "CAPEC-66"
    assert item.name == "SQL Injection"
    assert "CWE-89" in item.related_cwe_ids
    assert "CWE-564" in item.related_cwe_ids
    assert item.severity == "Very High"


def test_parse_nvd_cve_item():
    item = parse_nvd_cve_item(SAMPLE_NVD_CVE_DICT)
    assert item.cve_id == "CVE-2026-9999"
    assert item.severity == "CRITICAL"
    assert item.cvss_score == 9.8
    assert "CWE-78" in item.cwe_ids
    assert "command injection" in item.summary_en.lower()
    assert len(item.affected_packages) >= 1
    assert item.affected_packages[0]["package"] == "example-lib"
