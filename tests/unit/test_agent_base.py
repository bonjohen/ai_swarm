"""Tests for agents.base_agent and agents.registry."""

import json

import pytest
from pydantic import BaseModel

from agents.base_agent import AgentPolicy, BaseAgent, extract_json
from agents import registry


# --- Fixtures: a concrete test agent ---

class EchoInput(BaseModel):
    message: str

class EchoOutput(BaseModel):
    echoed: str


class EchoAgent(BaseAgent):
    AGENT_ID = "echo"
    VERSION = "0.1.0"
    SYSTEM_PROMPT = "You are an echo agent."
    USER_TEMPLATE = "Echo: {message}"
    INPUT_SCHEMA = EchoInput
    OUTPUT_SCHEMA = EchoOutput
    POLICY = AgentPolicy(allowed_local_models=["local-test"])

    def parse(self, response: str) -> dict:
        data = json.loads(response)
        return {"echoed": data["echoed"]}

    def validate(self, output: dict) -> None:
        if "echoed" not in output:
            raise ValueError("Missing 'echoed' key")


@pytest.fixture(autouse=True)
def clear_registry():
    registry.clear()
    yield
    registry.clear()


# --- Tests ---

def test_agent_has_required_attributes():
    agent = EchoAgent()
    assert agent.AGENT_ID == "echo"
    assert agent.VERSION == "0.1.0"
    assert agent.SYSTEM_PROMPT
    assert agent.USER_TEMPLATE
    assert agent.INPUT_SCHEMA is EchoInput
    assert agent.OUTPUT_SCHEMA is EchoOutput
    assert isinstance(agent.POLICY, AgentPolicy)


def test_build_prompt():
    agent = EchoAgent()
    sys, user = agent.build_prompt({"message": "hello"})
    assert sys == "You are an echo agent."
    assert user == "Echo: hello"


def test_parse_and_validate():
    agent = EchoAgent()
    result = agent.parse('{"echoed": "hello"}')
    assert result == {"echoed": "hello"}
    agent.validate(result)  # should not raise


def test_validate_raises_on_bad_output():
    agent = EchoAgent()
    with pytest.raises(ValueError, match="Missing 'echoed'"):
        agent.validate({"wrong_key": "x"})


def test_run_with_mock_model():
    agent = EchoAgent()

    def mock_model(sys_prompt, user_msg):
        return json.dumps({"echoed": user_msg})

    delta = agent.run({"message": "test"}, model_call=mock_model)
    assert delta["echoed"] == "Echo: test"


def test_run_without_model_raises():
    agent = EchoAgent()
    with pytest.raises(RuntimeError, match="model_call must be provided"):
        agent.run({"message": "test"})


def test_registry_register_and_get():
    agent = EchoAgent()
    registry.register(agent)
    assert registry.get_agent("echo") is agent


def test_registry_get_missing_raises():
    with pytest.raises(KeyError, match="Agent not registered"):
        registry.get_agent("nonexistent")


def test_registry_list_agents():
    registry.register(EchoAgent())
    assert "echo" in registry.list_agents()


# --- extract_json tests ---

class TestExtractJson:
    def test_clean_json_passthrough(self):
        raw = '{"key": "value"}'
        assert extract_json(raw) == '{"key": "value"}'

    def test_clean_json_with_whitespace(self):
        raw = '  \n{"key": "value"}\n  '
        assert extract_json(raw) == '{"key": "value"}'

    def test_markdown_fences_json_tag(self):
        raw = '```json\n{"key": "value"}\n```'
        assert extract_json(raw) == '{"key": "value"}'

    def test_markdown_fences_no_tag(self):
        raw = '```\n{"key": "value"}\n```'
        assert extract_json(raw) == '{"key": "value"}'

    def test_preamble_text(self):
        raw = 'Here is the result:\n{"key": "value"}'
        assert extract_json(raw) == '{"key": "value"}'

    def test_postamble_text(self):
        raw = '{"key": "value"}\n\nLet me know if you need anything else.'
        assert extract_json(raw) == '{"key": "value"}'

    def test_preamble_and_postamble(self):
        raw = 'Sure! Here you go:\n{"key": "value"}\nHope that helps!'
        assert extract_json(raw) == '{"key": "value"}'

    def test_nested_braces(self):
        raw = 'Result:\n{"outer": {"inner": "val"}}'
        result = extract_json(raw)
        parsed = json.loads(result)
        assert parsed == {"outer": {"inner": "val"}}

    def test_array_response(self):
        raw = 'Here:\n[{"a": 1}, {"b": 2}]'
        result = extract_json(raw)
        parsed = json.loads(result)
        assert parsed == [{"a": 1}, {"b": 2}]

    def test_no_json_falls_through(self):
        raw = 'no json here'
        assert extract_json(raw) == 'no json here'

    def test_run_uses_extract_json(self):
        """BaseAgent.run() should handle markdown-fenced responses."""
        agent = EchoAgent()

        def fenced_model(sys_prompt, user_msg):
            return '```json\n{"echoed": "' + user_msg + '"}\n```'

        delta = agent.run({"message": "test"}, model_call=fenced_model)
        assert delta["echoed"] == "Echo: test"
