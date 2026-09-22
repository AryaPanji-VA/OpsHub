import sys
from pathlib import Path
import os
import json
from unittest.mock import Mock, patch, MagicMock
sys.path.insert(0, str(Path(__file__).parent.parent))

from opshub.llm.mock import MockLLMProvider
from opshub.llm import get_llm_provider


def test_mock_provider_returns_plan():
    provider = MockLLMProvider()
    plan = provider.generate_plan("Test notes")
    assert plan.program is not None
    assert len(plan.tasks) > 0


def test_provider_selection_mock():
    with patch.dict(os.environ, {"LLM_PROVIDER": "mock"}):
        provider = get_llm_provider()
        assert isinstance(provider, MockLLMProvider)


def test_provider_selection_qwen_missing_api_key(monkeypatch):
    with patch.dict(os.environ, {"LLM_PROVIDER": "qwen"}, clear=True):
        os.environ["LLM_PROVIDER"] = "qwen"
        try:
            from opshub.llm.qwen import QwenProvider
            QwenProvider()
            assert False, "Should raise"
        except Exception as e:
            assert "GROQ_API_KEY" in str(e)


def test_schema_has_additional_properties_false():
    from opshub.models import OperationalPlan, Task, RiskFlag

    op_schema = OperationalPlan.model_json_schema()
    task_schema = Task.model_json_schema()
    rf_schema = RiskFlag.model_json_schema()

    assert op_schema.get("additionalProperties") is False
    assert task_schema.get("additionalProperties") is False
    assert rf_schema.get("additionalProperties") is False


def test_extra_fields_rejected(monkeypatch):
    from opshub.models import OperationalPlan, Task, RiskFlag

    try:
        OperationalPlan(
            program="Test",
            summary="Test",
            tasks=[{"id": "task-001", "title": "Test", "extra_field": "should fail"}],
            checks_required=[],
            risk_flags=[],
            next_action="wait_for_human",
        )
        assert False, "Should raise validation error"
    except Exception as e:
        assert "extra" in str(e).lower() or "unknown" in str(e).lower()


def test_provider_selection_unknown():
    with patch.dict(os.environ, {"LLM_PROVIDER": "unknown"}):
        try:
            get_llm_provider()
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "Unknown LLM_PROVIDER" in str(e)


def test_qwen_provider_valid_response(monkeypatch):
    os.environ["GROQ_API_KEY"] = "test_key"
    os.environ["MODEL_NAME"] = "test-model"
    os.environ["LLM_PROVIDER"] = "qwen"
    
    mock_response = {
        "program": "Test Program",
        "summary": "Test Summary",
        "tasks": [
            {
                "id": "task-001",
                "title": "Test Task",
                "division": "Ops",
                "pic": "Alice",
                "deadline": None,
                "budget_required": None,
                "priority": None,
                "status": None,
            }
        ],
        "checks_required": ["budget"],
        "risk_flags": [],
        "next_action": "wait_for_human",
    }
    
    mock_choice = Mock()
    mock_choice.message.content = json.dumps(mock_response)
    
    mock_result = MagicMock()
    mock_result.choices = [mock_choice]
    
    with patch("groq.Groq") as MockGroq:
        mock_client = Mock()
        mock_client.chat.completions.create.return_value = mock_result
        MockGroq.return_value = mock_client
        
        from opshub.llm.qwen import QwenProvider
        provider = QwenProvider()
        plan = provider.generate_plan("Test notes")
        
        assert plan.program == "Test Program"
        assert len(plan.tasks) == 1


def test_qwen_provider_empty_content(monkeypatch):
    os.environ["GROQ_API_KEY"] = "test_key"
    os.environ["MODEL_NAME"] = "test-model"
    os.environ["LLM_PROVIDER"] = "qwen"
    
    mock_choice = Mock()
    mock_choice.message.content = None
    
    mock_result = MagicMock()
    mock_result.choices = [mock_choice]
    
    with patch("groq.Groq") as MockGroq:
        mock_client = Mock()
        mock_client.chat.completions.create.return_value = mock_result
        MockGroq.return_value = mock_client
        
        from opshub.llm.qwen import QwenProvider
        provider = QwenProvider()
        
        try:
            provider.generate_plan("Test notes")
            assert False, "Should raise ValueError"
        except Exception as e:
            assert "empty" in str(e).lower()


def test_qwen_provider_empty_response(monkeypatch):
    os.environ["GROQ_API_KEY"] = "test_key"
    os.environ["MODEL_NAME"] = "test-model"
    os.environ["LLM_PROVIDER"] = "qwen"
    
    mock_choice = Mock()
    mock_choice.message.content = ""
    
    mock_result = MagicMock()
    mock_result.choices = [mock_choice]
    
    with patch("groq.Groq") as MockGroq:
        mock_client = Mock()
        mock_client.chat.completions.create.return_value = mock_result
        MockGroq.return_value = mock_client
        
        from opshub.llm.qwen import QwenProvider
        provider = QwenProvider()
        
        try:
            provider.generate_plan("Test notes")
            assert False, "Should raise ValueError"
        except Exception:
            pass


def test_task_schema_has_all_required_fields():
    from opshub.models import Task

    schema = Task.model_json_schema()
    required = set(schema.get("required", []))
    properties = set(schema.get("properties", {}).keys())

    assert required == properties


def test_nullable_fields_accept_none():
    from opshub.models import Task

    task = Task(
        id="t1",
        title="Test",
        division=None,
        pic=None,
        deadline=None,
        budget_required=None,
        priority=None,
        status=None,
    )
    assert task.budget_required is None


def test_missing_required_field_fails_validation():
    from opshub.models import Task

    try:
        Task(id="t1", title="Test")
        assert False, "Should raise validation error"
    except Exception:
        pass
