"""app/agent.py — Team Member A's AI Agent Interface.

Responsible for the `ask(question)` function that queries FalkorDB,
reasons over organizational ownership vs actual knowledge, and returns answers with citations.
"""
from typing import Any, Dict, Optional
import os


def ask(question: str) -> Optional[Dict[str, Any]]:
    """Execute the Lore agent on `question` and return answer with evidence.

    Until A implements the live LLM + FalkorDB chain, this function returns None,
    signaling to main.py to serve the validated stub contract with is_stub: true.
    """
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        # LLM not configured yet — fallback to stub
        return None

    # When A integrates their LangGraph / FalkorDB agent, live execution occurs here.
    return None
