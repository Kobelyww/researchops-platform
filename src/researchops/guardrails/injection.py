"""Prompt-injection defenses for untrusted tool observations.

Strategy: detect known injection patterns + canary tampering, then neutralize
by quoting untrusted content into a tagged block the system prompt tells the
model to treat as data, never as instructions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

INJECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("instruction_override", re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.I)),
    ("instruction_override", re.compile(r"disregard\s+(all\s+)?(previous|prior|your)\s+(instructions|rules|system)", re.I)),
    ("identity_override", re.compile(r"you\s+are\s+now\s+(a|an)\s+", re.I)),
    ("system_prompt_probe", re.compile(r"reveal|repeat|print\s+your\s+(system\s+prompt|instructions)", re.I)),
    ("secret_exfiltration", re.compile(r"(api[_-]?key|secret|token|password|credential)s?\s*[:=]", re.I)),
    ("exfiltration", re.compile(r"(send|post|upload|exfiltrate)\s+.*(http|ftp|webhook)", re.I)),
    ("tool_forge", re.compile(r"</?(system|assistant|tool)_?>", re.I)),
]

CANARY = "RESEARCHOPS-CANARY-7f3a9c"


@dataclass
class InjectionReport:
    is_suspicious: bool = False
    findings: list[str] = field(default_factory=list)


def scan(text: str) -> InjectionReport:
    findings: list[str] = []
    for label, pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            findings.append(label)
    if CANARY in text:
        findings.append("canary_tampering")
    return InjectionReport(is_suspicious=bool(findings), findings=findings)


def sanitize(text: str, max_chars: int = 8000) -> str:
    """Wrap untrusted content in an explicit data block; deflate forged role tags."""
    if len(text) > max_chars:
        text = text[:max_chars] + f" [truncated {len(text) - max_chars} chars]"
    deflated = re.sub(r"</?(system|assistant|developer|tool)_?>", "[tag]", text, flags=re.I)
    return f"<untrusted_content>\n{deflated}\n</untrusted_content>"
