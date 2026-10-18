"""tests/test_agent.py — Offline test suite for Lore AI agent."""
import json
from types import SimpleNamespace
from typing import Any, List
from unittest.mock import MagicMock

import pytest

from app import agent


class MockFunction:
    def __init__(self, name: str, arguments: dict):
        self.name = name
        self.arguments = json.dumps(arguments)


class MockToolCall:
    def __init__(self, call_id: str, name: str, arguments: dict):
        self.id = call_id
        self.type = "function"
        self.function = MockFunction(name, arguments)


class MockMessage:
    def __init__(self, content: str = None, tool_calls: List[MockToolCall] = None):
        self.role = "assistant"
        self.content = content
        self.tool_calls = tool_calls or []


class MockChoice:
    def __init__(self, message: MockMessage):
        self.message = message


class MockCompletion:
    def __init__(self, message: MockMessage):
        self.choices = [MockChoice(message)]


class ScriptedLLMClient:
    """Fake LLM client that returns scripted responses offline."""

    def __init__(self, responses: List[MockMessage]):
        self.responses = list(responses)
        self.call_history: List[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs) -> MockCompletion:
        self.call_history.append(kwargs)
        if kwargs.get("tool_choice") == "none":
            # Forced final answer
            return MockCompletion(MockMessage(content="Forced final answer without tools."))
        if self.responses:
            next_msg = self.responses.pop(0)
            return MockCompletion(next_msg)
        return MockCompletion(MockMessage(content="Default fallback answer."))


@pytest.fixture(autouse=True)
def stub_environment(monkeypatch):
    """Ensure all tests run offline with USE_STUBS=1."""
    monkeypatch.setenv("USE_STUBS", "1")
    monkeypatch.setenv("LLM_API_KEY", "fake_key_for_testing")


def test_calls_tool_then_answers():
    """Verify tool execution, steps recording, source numbering, and stub status."""
    script = [
        MockMessage(
            tool_calls=[MockToolCall("call_1", "who_owns", {"thing": "sig-node"})]
        ),
        MockMessage(
            content="While SIG Node has official leaders [1], others do significant work."
        ),
    ]
    client = ScriptedLLMClient(script)

    result = agent.ask("Who owns SIG Node?", client=client)

    assert result["question"] == "Who owns SIG Node?"
    assert len(result["steps"]) == 1
    assert result["steps"][0]["tool"] == "who_owns"
    assert result["steps"][0]["input"]["thing"] == "sig-node"
    assert result["is_stub"] is True
    assert len(result["sources"]) > 0
    assert result["sources"][0]["n"] == 1
    assert "[1]" in result["answer"]


def test_two_tool_calls_in_one_response():
    """Verify multi-tool responses run both tools and merge evidence without duplicate nodes/edges."""
    script = [
        MockMessage(
            tool_calls=[
                MockToolCall("call_1", "who_owns", {"thing": "sig-node"}),
                MockToolCall("call_2", "who_knows", {"thing": "sig-node"}),
            ]
        ),
        MockMessage(
            content="Comparing official owners [1] with active knowers [2] shows key differences."
        ),
    ]
    client = ScriptedLLMClient(script)

    result = agent.ask("Who owns vs knows SIG Node?", client=client)

    assert len(result["steps"]) == 2
    assert result["steps"][0]["tool"] == "who_owns"
    assert result["steps"][1]["tool"] == "who_knows"

    nodes = result["evidence"]["nodes"]
    edges = result["evidence"]["edges"]

    # Verify no duplicate nodes
    node_ids = [n["id"] for n in nodes]
    assert len(node_ids) == len(set(node_ids))

    # Verify no duplicate edges
    edge_keys = [(e["source"], e["target"], e.get("relation", "")) for e in edges]
    assert len(edge_keys) == len(set(edge_keys))


def test_answer_preserves_non_source_brackets_and_renumbers():
    """Verify non-source brackets like [2019-2021] and [2024] are kept while real sources are renumbered."""
    script = [
        MockMessage(
            tool_calls=[MockToolCall("call_1", "who_owns", {"thing": "sig-node"})]
        ),
        # Returns [2019-2021] (year range), [2024] (year), and [2] (real 2nd source in stub)
        MockMessage(
            content="Since [2019-2021] it changed [2]. In [2024] new rules applied."
        ),
    ]
    client = ScriptedLLMClient(script)

    result = agent.ask("Test citation cleanup", client=client)

    # Non-source brackets must be preserved
    assert "[2019-2021]" in result["answer"]
    assert "[2024]" in result["answer"]

    # Real sources renumbered 1..k
    assert len(result["sources"]) == 1
    assert result["sources"][0]["n"] == 1
    assert "[1]" in result["answer"]
    # No stray spaces before punctuation
    assert "[1]." in result["answer"]


def test_all_tool_calls_failed_returns_none(monkeypatch):
    """If every tool call fails (e.g. FalkorDB is down), ask() returns None to allow stub fallback."""
    def broken_who_owns(**kwargs):
        raise RuntimeError("Connection refused")

    monkeypatch.setitem(agent.TOOL_CALLABLES, "who_owns", broken_who_owns)

    script = [
        MockMessage(
            tool_calls=[MockToolCall("call_1", "who_owns", {"thing": "sig-node"})]
        ),
        MockMessage(content="The data does not show it."),
    ]
    client = ScriptedLLMClient(script)

    result = agent.ask("Who owns SIG Node?", client=client)
    # Must return None so server can fall back to the stub
    assert result is None


def test_partial_tool_error_masks_raw_error_text(monkeypatch):
    """When a tool fails, steps[].summary shows a generic message rather than raw host/port errors."""
    def broken_who_owns(**kwargs):
        raise RuntimeError("Error 111 connecting to localhost:6379")

    monkeypatch.setitem(agent.TOOL_CALLABLES, "who_owns", broken_who_owns)

    script = [
        MockMessage(
            tool_calls=[
                MockToolCall("call_1", "who_owns", {"thing": "sig-node"}),
                MockToolCall("call_2", "who_knows", {"thing": "sig-node"}),
            ]
        ),
        MockMessage(content="Found active knowers [1] despite who_owns failure."),
    ]
    client = ScriptedLLMClient(script)

    result = agent.ask("Who owns vs knows SIG Node?", client=client)
    assert result is not None
    # Raw connection text must NOT leak into summary
    assert "localhost:6379" not in result["steps"][0]["summary"]
    assert result["steps"][0]["summary"] == "Tool execution failed."



def test_stops_at_six_tool_calls_and_forces_answer():
    """Verify model execution loop stops at max 6 tool calls and calls with tool_choice='none'."""
    # Script that endlessly requests more tools
    endless_calls = [
        MockMessage(
            tool_calls=[MockToolCall(f"call_{i}", "who_owns", {"thing": "sig-node"})]
        )
        for i in range(10)
    ]
    client = ScriptedLLMClient(endless_calls)

    result = agent.ask("Infinite loop test", client=client)

    # Must cap at 6 tool calls
    assert len(result["steps"]) == 6
    # Last call must have enforced tool_choice="none"
    last_call = client.call_history[-1]
    assert last_call.get("tool_choice") == "none"
    assert result["answer"] == "Forced final answer without tools."


def test_every_edge_source_and_target_exist_in_nodes():
    """Verify graph integrity: every edge's source and target must exist in evidence nodes."""
    script = [
        MockMessage(
            tool_calls=[
                MockToolCall("call_1", "who_owns", {"thing": "sig-node"}),
                MockToolCall("call_2", "why", {"thing": "KEP-4671"}),
            ]
        ),
        MockMessage(
            content="SIG Node and KEP-4671 show the organizational and decision trail [1] [2]."
        ),
    ]
    client = ScriptedLLMClient(script)

    result = agent.ask("Graph integrity test", client=client)

    node_ids = {n["id"] for n in result["evidence"]["nodes"]}
    for edge in result["evidence"]["edges"]:
        assert edge["source"] in node_ids, f"Edge source {edge['source']} missing from nodes"
        assert edge["target"] in node_ids, f"Edge target {edge['target']} missing from nodes"


def test_ask_returns_none_when_no_key_and_no_client(monkeypatch):
    """Problem 1: With no LLM_API_KEY and no client passed, ask() returns None."""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    res = agent.ask("Who owns SIG Node?", client=None)
    assert res is None


def test_empty_env_vars_fallback_to_defaults(monkeypatch):
    """Problem 2: Empty LLM_BASE_URL and LLM_MODEL fallback to defaults."""
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setenv("LLM_API_KEY", "fake_key")

    created_kwargs = {}

    def mock_openai_init(**kwargs):
        created_kwargs.update(kwargs)
        fake = MagicMock()
        fake.chat.completions.create.return_value = MockCompletion(MockMessage(content="ok"))
        return fake

    monkeypatch.setattr(agent, "OpenAI", mock_openai_init)
    res = agent.ask("Hello")
    assert res is not None
    assert created_kwargs.get("base_url") == "https://generativelanguage.googleapis.com/v1beta/openai/"
    assert created_kwargs.get("max_retries") == 0


def test_multi_round_tool_cap_answers_all_tool_calls_and_includes_tools_in_final():
    """Problem 3: 4 tool calls in round 1 + 4 in round 2: all 8 answered, tools passed with tool_choice='none'."""
    round1_calls = [
        MockToolCall(f"call_{i}", "who_owns", {"thing": "sig-node"})
        for i in range(1, 5)
    ]
    round2_calls = [
        MockToolCall(f"call_{i}", "who_owns", {"thing": "sig-node"})
        for i in range(5, 9)
    ]

    script = [
        MockMessage(tool_calls=round1_calls),
        MockMessage(tool_calls=round2_calls),
    ]
    client = ScriptedLLMClient(script)

    result = agent.ask("Test 4+4 tool cap", client=client)

    # Must execute exactly 6 calls overall
    assert len(result["steps"]) == 6

    # Verify that in the call with tool_choice="none", all tool calls from round 2 are answered
    forced_call = client.call_history[-1]
    assert forced_call.get("tool_choice") == "none"
    assert forced_call.get("tools") == agent.TOOL_DEFINITIONS

    # Check history in forced_call: every tool_call_id from 1 to 8 must have a matching tool message
    messages = forced_call["messages"]
    tool_reply_ids = {m["tool_call_id"] for m in messages if isinstance(m, dict) and m.get("role") == "tool"}
    for i in range(1, 9):
        assert f"call_{i}" in tool_reply_ids

    # Calls 7 and 8 should have been marked as skipped due to tool limit
    skipped_replies = [
        m for m in messages
        if isinstance(m, dict) and m.get("role") == "tool" and "skipped: tool limit reached" in str(m.get("content"))
    ]
    assert len(skipped_replies) == 2


def test_non_dict_tool_arguments_handled_gracefully():
    """Problem 8: Non-dict tool arguments (None, list, string) don't crash the request."""
    # Custom mock function with non-dict json arguments
    class CustomMockFunction:
        def __init__(self, name: str, args_str: str):
            self.name = name
            self.arguments = args_str

    class CustomMockToolCall:
        def __init__(self, call_id: str, name: str, args_str: str):
            self.id = call_id
            self.type = "function"
            self.function = CustomMockFunction(name, args_str)

    script = [
        MockMessage(tool_calls=[
            CustomMockToolCall("call_null", "who_owns", "null"),
            CustomMockToolCall("call_list", "who_owns", "[\"item\"]"),
            CustomMockToolCall("call_str", "who_owns", "\"just string\""),
        ]),
        MockMessage(tool_calls=[
            MockToolCall("call_valid", "who_owns", {"thing": "sig-node"}),
        ]),
        MockMessage(content="Handled non-dict tool args safely and found leaders [1]."),
    ]
    client = ScriptedLLMClient(script)

    result = agent.ask("Test malformed args", client=client)
    assert result is not None
    assert len(result["steps"]) == 4
    for i in range(3):
        assert result["steps"][i]["input"] == {}
    assert result["steps"][3]["input"] == {"thing": "sig-node"}



def test_grouped_citations_expanded_and_renumbered():
    """Problem 9: Grouped citations like [1, 2] and [1-3] are expanded and both sources preserved."""
    script = [
        MockMessage(
            tool_calls=[
                MockToolCall("call_1", "who_owns", {"thing": "sig-node"}),
                MockToolCall("call_2", "who_knows", {"thing": "sig-node"}),
            ]
        ),
        MockMessage(
            content="Official leaders and contributors are documented in [1, 2] and detailed in [1-2]."
        ),
    ]
    client = ScriptedLLMClient(script)

    result = agent.ask("Citation groups", client=client)
    assert len(result["sources"]) == 2
    assert "[1]" in result["answer"]
    assert "[2]" in result["answer"]
    # Group [1, 2] expanded into [1][2]
    assert "[1, 2]" not in result["answer"]
    assert "[1-2]" not in result["answer"]


def test_thing_unmodified_gang_scheduling():
    """Problem 7: normalize_arguments does not rewrite or hyphenate strings like 'Gang Scheduling'."""
    script = [
        MockMessage(
            tool_calls=[MockToolCall("call_1", "who_owns", {"thing": "  Gang Scheduling  "})]
        ),
        MockMessage(content="Gang scheduling is tracked under KEP-4671 [1]."),
    ]
    client = ScriptedLLMClient(script)

    result = agent.ask("Who owns Gang Scheduling?", client=client)
    assert result["steps"][0]["input"]["thing"] == "Gang Scheduling"


def test_slow_client_respects_deadline_timeout(monkeypatch):
    """Problem 4: Timeout parameter passed to client call adapts to remaining time budget."""
    recorded_timeouts = []

    def mock_create(**kwargs):
        recorded_timeouts.append(kwargs.get("timeout"))
        return MockCompletion(MockMessage(content="Answer within time."))

    client = MagicMock()
    client.chat.completions.create = mock_create

    # Artificially advance time so 30 seconds have elapsed since start_time
    time_states = [100.0, 130.0, 130.0, 130.0]
    monkeypatch.setattr(agent.time, "time", lambda: time_states.pop(0) if time_states else 130.0)

    result = agent.ask("Timeout test", client=client)
    assert result is not None
    assert len(recorded_timeouts) > 0
    # Remaining time is 55 - 30 = 25s, so timeout should be 25s
    assert recorded_timeouts[0] <= 25.0


def test_format_page_fields_excludes_folder_reviewers():
    """Verify that folder reviewers are NOT included in official_owners (only approvers)."""
    fake_tool_res = [{
        "tool": "who_owns",
        "data": {
            "approvers": [{"login": "alice", "source": "pkg/OWNERS"}],
            "reviewers": [{"login": "bob", "source": "pkg/OWNERS"}],
        }
    }]
    owners, knowers, trail = agent.format_page_fields(fake_tool_res)
    owner_logins = [o["login"] for o in owners]
    assert "alice" in owner_logins
    assert "bob" not in owner_logins

