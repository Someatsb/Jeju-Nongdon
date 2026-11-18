"""도구 등록부(Task 18) — 이름·입력 모델·출력 모델·함수를 묶고, 호출을 기록하며 실행한다.

- schemas(): LLM에 보일 도구 정의(JSON Schema). 설명에 숫자를 쓰면 등록이 거부된다(전송 거름망이 숫자를 막는다).
- dispatch(): 잘못된 호출(없는 도구·인자 오류·ToolError·도구 내부 오류·결과 형식 오류)은 예외 대신 고칠 수 있는 한국어 error 기록으로 돌려준다.
"""
import inspect
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from app.tools.models import ToolLog, ToolRecord


class ToolError(Exception):
    """도구가 일을 거절했다. 메시지는 모델이 읽고 고칠 수 있는 한국어 문장이다."""


_DIGIT = re.compile(r"[0-9０-９]")


def _descriptions(node: Any):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "description" and isinstance(value, str):
                yield value
            yield from _descriptions(value)
    elif isinstance(node, list):
        for value in node:
            yield from _descriptions(value)


def _arg_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        where = ".".join(str(p) for p in err["loc"]) or "입력"
        reason = "필수 값이 없습니다" if err["type"] == "missing" else err["msg"]
        parts.append(f"{where}: {reason}")
    return "인자 오류 - " + "; ".join(parts)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, tuple[type[BaseModel], type[BaseModel], Callable[[Any], Any]]] = {}

    def register(self, name: str, input_model: type[BaseModel], output_model: type[BaseModel],
                 fn: Callable[[Any], Any]) -> None:
        if name in self._tools:
            raise ValueError(f"도구 '{name}'은 이미 등록되어 있습니다")
        if not inspect.cleandoc(input_model.__doc__ or ""):
            raise ValueError(f"도구 '{name}'의 입력 모델에 설명(독스트링)이 없습니다")
        bad = [t for t in _descriptions(input_model.model_json_schema()) if _DIGIT.search(t)]
        if bad:
            raise ValueError(f"도구 '{name}'의 설명에 숫자가 있습니다: {bad[0]}")
        self._tools[name] = (input_model, output_model, fn)

    def schemas(self) -> list[dict[str, Any]]:
        return [{"name": name, "description": inspect.cleandoc(inp.__doc__ or ""),
                 "input_schema": inp.model_json_schema()}
                for name, (inp, _out, _fn) in self._tools.items()]

    def dispatch(self, name: str, args: dict[str, Any], log: ToolLog) -> ToolRecord:
        record = self._run(name, args)
        log.calls.append(record)
        return record

    def _run(self, name: str, args: dict[str, Any]) -> ToolRecord:
        if name not in self._tools:
            return ToolRecord(name=name, args=args, ok=False,
                              error=f"모르는 도구입니다: {name}. 쓸 수 있는 도구: {', '.join(self._tools)}")
        input_model, output_model, fn = self._tools[name]
        try:
            parsed = input_model.model_validate(args)
        except ValidationError as exc:
            return ToolRecord(name=name, args=args, ok=False, error=_arg_error(exc))
        try:
            out = fn(parsed)
        except ToolError as exc:
            return ToolRecord(name=name, args=args, ok=False, error=str(exc))
        except Exception as exc:  # 도구 안의 뜻밖의 오류도 루프 밖으로 새지 않게 기록한다
            return ToolRecord(name=name, args=args, ok=False,
                              error=f"도구 내부 오류 - {type(exc).__name__}. 다른 방법으로 다시 시도하거나 직원에게 넘기세요")
        try:
            result = output_model.model_validate(out).model_dump(mode="json")
        except ValidationError:
            return ToolRecord(name=name, args=args, ok=False,
                              error="도구 결과 형식 오류 - 도구의 문제입니다. 다른 방법을 쓰거나 직원에게 넘기세요")
        return ToolRecord(name=name, args=args, ok=True, result=result)
