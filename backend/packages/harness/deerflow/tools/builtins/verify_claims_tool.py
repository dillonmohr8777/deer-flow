"""verify_claims: fact-check an outbound draft against evidence gathered in this run."""

from __future__ import annotations

import json
import logging

from langchain.tools import tool
from langchain_core.messages import ToolMessage

from deerflow.factcheck import Evidence, verify_draft
from deerflow.tools.types import Runtime

logger = logging.getLogger(__name__)


def _run_evidence(runtime: Runtime) -> list[Evidence]:
    """Successful tool outputs from this run (tool results are the run's evidence)."""
    out = []
    for m in (runtime.state or {}).get("messages", []):
        if isinstance(m, ToolMessage) and m.name != "verify_claims" and m.status != "error" and isinstance(m.content, str):
            out.append(Evidence(m.name or f"tool:{m.tool_call_id}", m.content))
    return out


def _model_judge(claim: str, snippets: list[str]) -> str | None:
    """Optional small-model tiebreak for ambiguous claims, via the default configured model."""
    try:
        from deerflow.models import create_chat_model

        prompt = f"Does the evidence support this claim? Answer exactly one word: supported, unsupported or contradicted.\nClaim: {claim}\nEvidence:\n" + "\n".join(snippets)
        return str(create_chat_model(thinking_enabled=False).invoke(prompt).content).strip().lower()
    except Exception:  # judge is best-effort; the claim stays unverifiable
        logger.warning("verify_claims judge failed", exc_info=True)
        return None


@tool("verify_claims", parse_docstring=True)
def verify_claims_tool(runtime: Runtime, draft: str, evidence: list[dict[str, str]] | None = None, use_model: bool = False) -> str:
    """Fact-check a draft's numbers, dates and named sources before proposing or sending it.

    ALWAYS call this on any outbound draft (client email, Slack post, report copy)
    before presenting it to the user. Evidence is every successful tool output in
    this run plus anything you pass in. Returns JSON: ``gate`` is ``block`` (a claim
    is contradicted: fix the draft, do not propose it), ``flag`` (unsupported claims:
    cite a source or remove them, or tell the user they are unsourced) or ``pass``.
    Missing data is unavailable, never 0; "up/down X%" needs before/after values from
    one source; platform labels (e.g. Reddit Ads) must match the data's real source.

    Args:
        draft: The full draft text to check.
        evidence: Optional extra evidence, each item ``{"source": "<label or path/url>", "text": "<content>"}``.
        use_model: Let a small model settle ambiguous claims only (default off).
    """
    items = _run_evidence(runtime) + [Evidence(str(e.get("source", "provided")), str(e.get("text", ""))) for e in evidence or [] if isinstance(e, dict)]
    return json.dumps(verify_draft(draft, items, judge=_model_judge if use_model else None).to_dict(), ensure_ascii=False)
