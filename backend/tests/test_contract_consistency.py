"""契约一致性：shared/contracts/control-message.schema.json ↔ pydantic 镜像。

TS 三向比对由桌面端类型检查覆盖；这里保证 schema 的 type 枚举、required 字段、
字段集合与 enum 取值和后端模型一致。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

import pytest

from app.transport.messages import (
    PAYLOAD_MODELS,
    PROTOCOL_VERSION,
    Capabilities,
    CharacterStateView,
    ControlMessage,
    MessageType,
    MessageView,
    TurnView,
    VoiceState,
)

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "shared" / "contracts"
SCHEMA_PATH = CONTRACTS_DIR / "control-message.schema.json"
PROTOCOL_DOC_PATH = CONTRACTS_DIR / "protocol.md"

NESTED_MODELS: dict[str, type] = {
    "capabilities": Capabilities,
    "messageView": MessageView,
    "turnView": TurnView,
    "voiceState": VoiceState,
    "characterStatePayload": CharacterStateView,
}


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _required_fields(model: type) -> set[str]:
    return {name for name, field in model.model_fields.items() if field.is_required()}


def _assert_definition_matches(definition: dict[str, Any], model: type) -> None:
    assert definition["type"] == "object"
    assert definition.get("additionalProperties") is False
    assert set(definition.get("properties", {})) == set(model.model_fields)
    assert set(definition.get("required", [])) == _required_fields(model), model.__name__

    for name, field in model.model_fields.items():
        if get_origin(field.annotation) is Literal:
            expected = set(get_args(field.annotation))
            actual = definition["properties"][name].get("enum")
            assert set(actual or []) == expected, f"{model.__name__}.{name}"


def _type_branches(schema: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for branch in schema["allOf"]:
        type_value = branch["if"]["properties"]["type"]["const"]
        reference = branch["then"]["properties"]["payload"]["$ref"]
        assert reference.startswith("#/definitions/"), reference
        mapping[type_value] = reference.rsplit("/", 1)[-1]
    return mapping


def test_envelope_matches_pydantic(schema: dict[str, Any]) -> None:
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == set(ControlMessage.model_fields)
    assert set(schema["required"]) == _required_fields(ControlMessage)
    assert schema["properties"]["protocol"]["const"] == PROTOCOL_VERSION
    assert get_args(ControlMessage.model_fields["protocol"].annotation) == (PROTOCOL_VERSION,)


def test_type_enum_matches_message_type(schema: dict[str, Any]) -> None:
    schema_types = set(schema["properties"]["type"]["enum"])
    pydantic_types = {item.value for item in MessageType}

    assert schema_types == pydantic_types
    assert set(PAYLOAD_MODELS) == set(MessageType)


def test_every_type_has_payload_definition(schema: dict[str, Any]) -> None:
    mapping = _type_branches(schema)

    assert set(mapping) == {item.value for item in MessageType}

    for type_value, definition_name in mapping.items():
        definition = schema["definitions"][definition_name]
        model = PAYLOAD_MODELS[MessageType(type_value)]
        _assert_definition_matches(definition, model)


def test_nested_snapshot_definitions_match_pydantic(schema: dict[str, Any]) -> None:
    for name, model in NESTED_MODELS.items():
        _assert_definition_matches(schema["definitions"][name], model)


def test_all_definitions_are_closed_objects_and_covered(schema: dict[str, Any]) -> None:
    definitions = schema["definitions"]
    covered = set(_type_branches(schema).values()) | set(NESTED_MODELS)

    assert set(definitions) == covered

    for name, definition in definitions.items():
        assert definition["type"] == "object", name
        assert definition.get("additionalProperties") is False, name
        assert isinstance(definition.get("properties"), dict), name


def test_protocol_doc_mentions_every_type(schema: dict[str, Any]) -> None:
    del schema
    document = PROTOCOL_DOC_PATH.read_text(encoding="utf-8")

    assert "vob/1" in document
    for item in MessageType:
        assert item.value in document, f"protocol.md 缺少 {item.value}"
