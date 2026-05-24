"""测试 artifact 读写 — 特别是 write_json_artifact 的原子写入。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from gearbox.agents.shared.artifacts import read_json_artifact, write_json_artifact


class TestWriteJsonArtifactBasic:
    """基础写入/读取功能。"""

    def test_writes_and_reads_back(self, tmp_path: Path) -> None:
        path = tmp_path / "output.json"
        payload = {"key": "value", "nested": {"a": 1}}
        write_json_artifact(path, payload)
        assert read_json_artifact(path) == payload

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        path = tmp_path / "deep" / "nested" / "dir" / "out.json"
        write_json_artifact(path, {"ok": True})
        assert path.exists()

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "overwrite.json"
        write_json_artifact(path, {"old": True})
        write_json_artifact(path, {"new": False})
        assert read_json_artifact(path) == {"new": False}

    def test_handles_pydantic_models(self, tmp_path: Path) -> None:
        from pydantic import BaseModel

        class MyModel(BaseModel):
            name: str
            count: int

        path = tmp_path / "model.json"
        write_json_artifact(path, MyModel(name="test", count=42))
        result = read_json_artifact(path)
        assert result["name"] == "test"
        assert result["count"] == 42


class TestWriteJsonArtifactAtomic:
    """原子写入行为验证：write-to-temp + rename 模式。"""

    def test_no_partial_file_on_failure(self, tmp_path: Path, monkeypatch) -> None:
        """写入过程中抛异常时，目标文件不应存在（或保持旧内容不变）。"""
        target = tmp_path / "atomic.json"

        # 先写入一个有效文件
        write_json_artifact(target, {"original": True})
        assert read_json_artifact(target) == {"original": True}

        # 让 os.write 在第二次调用时抛异常，模拟中断
        original_write = os.write
        call_count = [0]

        def failing_write(fd: int, data: bytes) -> int:
            call_count[0] += 1
            if call_count[0] > 0:  # 第一次就失败
                raise OSError("simulated crash")
            return original_write(fd, data)

        monkeypatch.setattr(os, "write", failing_write)

        with pytest.raises(OSError, match="simulated crash"):
            write_json_artifact(target, {"new_data": True})

        # 目标文件应保持原始内容，不受影响
        assert read_json_artifact(target) == {"original": True}

    def test_temp_file_cleaned_up_after_success(self, tmp_path: Path) -> None:
        """成功写入后 .tmp 文件不应残留。"""
        target = tmp_path / "clean.json"
        write_json_artifact(target, {"data": 1})

        # 同目录下不应有 .tmp 文件
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_temp_file_cleaned_up_on_error(self, tmp_path: Path, monkeypatch) -> None:
        """写入失败后 .tmp 文件不应残留。"""
        target = tmp_path / "error_cleanup.json"

        def failing_rename(src: str, dst: str) -> None:
            raise OSError("rename failed")

        monkeypatch.setattr(os, "rename", failing_rename)

        with pytest.raises(OSError):
            write_json_artifact(target, {"data": 1})

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_atomic_replace_preserves_content(self, tmp_path: Path) -> None:
        """原子替换后文件内容完整正确。"""
        target = tmp_path / "replace.json"
        large_payload = {f"key_{i}": f"value_{i}" for i in range(500)}
        write_json_artifact(target, large_payload)
        result = read_json_artifact(target)
        assert result == large_payload
