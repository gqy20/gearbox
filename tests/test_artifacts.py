"""测试 artifacts 模块 — artifact 读写与类型校验。"""

import json

import pytest

from gearbox.agents.shared.artifacts import read_json_artifact, write_json_artifact


class TestReadJsonArtifact:
    """read_json_artifact 类型校验测试。"""

    def test_valid_dict_returns_data(self, tmp_path) -> None:
        path = tmp_path / "valid.json"
        data = {"key": "value", "nested": {"a": 1}}
        path.write_text(json.dumps(data), encoding="utf-8")

        result = read_json_artifact(path)
        assert result == data

    def test_list_json_raises_typeerror(self, tmp_path) -> None:
        path = tmp_path / "list.json"
        path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

        with pytest.raises(TypeError, match="Expected dict"):
            read_json_artifact(path)

    def test_scalar_json_raises_typeerror(self, tmp_path) -> None:
        path = tmp_path / "scalar.json"
        path.write_text(json.dumps("just a string"), encoding="utf-8")

        with pytest.raises(TypeError, match="Expected dict"):
            read_json_artifact(path)

    def test_null_json_raises_typeerror(self, tmp_path) -> None:
        path = tmp_path / "null.json"
        path.write_text("null", encoding="utf-8")

        with pytest.raises(TypeError, match="Expected dict"):
            read_json_artifact(path)

    def test_number_json_raises_typeerror(self, tmp_path) -> None:
        path = tmp_path / "number.json"
        path.write_text("42", encoding="utf-8")

        with pytest.raises(TypeError, match="Expected dict"):
            read_json_artifact(path)


class TestWriteJsonArtifact:
    """write_json_artifact 基本功能测试。"""

    def test_write_and_read_roundtrip(self, tmp_path) -> None:
        path = tmp_path / "roundtrip.json"
        payload = {"issues": [{"title": "Bug", "severity": "high"}]}
        write_json_artifact(path, payload)

        result = read_json_artifact(path)
        assert result == payload
