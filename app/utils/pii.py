"""PII detection and redaction utilities."""

from __future__ import annotations

import re
from typing import Any


# Pattern definitions for PII types
PII_PATTERNS = {
    "email": re.compile(
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        re.IGNORECASE
    ),
    "phone": re.compile(
        r'''
        (?:
            (?:\+?1[-.\s]?)?              # Optional country code
            (?:\(?\d{3}\)?[-.\s]?)        # Area code
            \d{3}[-.\s]?\d{4}             # Main number
        )
        ''',
        re.VERBOSE
    ),
    "ssn": re.compile(
        r'\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b'
    ),
    "credit_card": re.compile(
        r'\b(?:\d{4}[-\s]?){3}\d{4}\b'
    ),
    "ip_address": re.compile(
        r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
    ),
}

# Redaction placeholders
REDACTION_MASKS = {
    "email": "[EMAIL_REDACTED]",
    "phone": "[PHONE_REDACTED]",
    "ssn": "[SSN_REDACTED]",
    "credit_card": "[CC_REDACTED]",
    "ip_address": "[IP_REDACTED]",
}


def redact_pii(text: str, pii_types: list[str] | None = None) -> str:
    """
    Redact PII from text using regex patterns.
    
    Args:
        text: Input text to redact
        pii_types: List of PII types to redact. If None, redacts all types.
                  Options: email, phone, ssn, credit_card, ip_address
    
    Returns:
        Text with PII replaced by redaction masks
    """
    if not text:
        return text
    
    types_to_redact = pii_types or list(PII_PATTERNS.keys())
    result = text
    
    for pii_type in types_to_redact:
        if pii_type in PII_PATTERNS:
            pattern = PII_PATTERNS[pii_type]
            mask = REDACTION_MASKS[pii_type]
            result = pattern.sub(mask, result)
    
    return result


def redact_dict(data: dict[str, Any], pii_types: list[str] | None = None) -> dict[str, Any]:
    """
    Recursively redact PII from dictionary values.
    
    Args:
        data: Dictionary to redact
        pii_types: List of PII types to redact
    
    Returns:
        Dictionary with PII redacted from string values
    """
    result = {}
    
    for key, value in data.items():
        if isinstance(value, str):
            result[key] = redact_pii(value, pii_types)
        elif isinstance(value, dict):
            result[key] = redact_dict(value, pii_types)
        elif isinstance(value, list):
            result[key] = [
                redact_dict(item, pii_types) if isinstance(item, dict)
                else redact_pii(item, pii_types) if isinstance(item, str)
                else item
                for item in value
            ]
        else:
            result[key] = value
    
    return result


def detect_pii(text: str) -> dict[str, list[str]]:
    """
    Detect PII in text and return found matches by type.
    
    Args:
        text: Input text to scan
    
    Returns:
        Dictionary mapping PII type to list of matches found
    """
    if not text:
        return {}
    
    found: dict[str, list[str]] = {}
    
    for pii_type, pattern in PII_PATTERNS.items():
        matches = pattern.findall(text)
        if matches:
            found[pii_type] = matches
    
    return found


def has_pii(text: str) -> bool:
    """Check if text contains any PII."""
    return bool(detect_pii(text))


# Privacy-safe logging filter
class PIIFilter:
    """Filter for use with Python logging to redact PII."""
    
    def __init__(self, pii_types: list[str] | None = None):
        self.pii_types = pii_types
    
    def filter(self, record) -> bool:
        """Filter and modify log record to redact PII."""
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            record.msg = redact_pii(record.msg, self.pii_types)
        if hasattr(record, 'args') and record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: redact_pii(str(v), self.pii_types) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    redact_pii(str(arg), self.pii_types) if isinstance(arg, str) else arg
                    for arg in record.args
                )
        return True
