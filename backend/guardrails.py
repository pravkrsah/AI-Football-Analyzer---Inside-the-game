"""
Input safety guardrails for the AI Pundit chat.

Pre-filter (no API call) blocks only genuine prompt-injection attempts and
oversized inputs. Off-topic questions are NOT blocked here — the model handles
them by pivoting the answer back to the match in a witty way (desired behaviour).

SQL injection is not a concern: all database.py queries use parameterised
?-placeholder statements so user input never reaches SQL as raw text.
"""
import re

_MAX_LEN = 500

# Patterns that indicate deliberate prompt-injection rather than a genuine question.
_INJECTION_RE = re.compile(
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?"
    r"|forget\s+(everything|all|your|prior|previous)"
    r"|you\s+are\s+now\s+(a|an)\s"
    r"|act\s+as\s+(if\s+you\s+(are|were)|a\s+different)"
    r"|new\s+(system\s+)?instructions?\s*:"
    r"|<\s*/?system\s*>"
    r"|\[\s*system\s*\]"
    r"|override\s+(your\s+)?(instructions?|programming|rules|guidelines?)"
    r"|disregard\s+(all\s+)?(previous|prior|your)"
    r"|jailbreak"
    r"|developer\s+mode"
    r"|DAN\s+mode"
    r"|pretend\s+(you\s+are|to\s+be)\s+a\s+different"
    r"|you\s+must\s+(now|always|only)\s+(ignore|forget|obey)",
    re.IGNORECASE,
)


def check_question(question: str) -> tuple[bool, str]:
    """
    Return (is_safe, rejection_message).

    - is_safe=True  → pass to the AI pundit normally
    - is_safe=False → return rejection_message directly, no GPT call made
    """
    if not question or not question.strip():
        return False, "Please ask a question about the match."

    q = question.strip()

    if len(q) > _MAX_LEN:
        return False, f"Keep it under {_MAX_LEN} characters and I'll give you my verdict!"

    if _INJECTION_RE.search(q):
        return False, "Nice try, but I'm a football pundit — not a hacker's assistant. Ask me about the match!"

    return True, ""
