from __future__ import annotations

import json
import asyncio
from pathlib import Path

import jsonschema
import pytest

from cst_trace import trace_function


def test_trace_records_success_and_separates_vba(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CST_TRACE_ROOT", str(tmp_path))
    monkeypatch.setenv("CST_TRACE_ID", "unit-trace")

    @trace_function
    def run_vba_tool(vba_code: str, password: str) -> dict[str, bool]:
        return {"ok": True}

    assert run_vba_tool("Sub Main()\nEnd Sub", "do-not-log") == {"ok": True}
    trace_path = tmp_path / "unit-trace" / "trace.jsonl"
    event = json.loads(trace_path.read_text(encoding="utf-8").splitlines()[0])
    schema_path = Path(__file__).resolve().parents[3] / "brain" / "schemas" / "trace-event.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(event, schema)
    assert event["status"] == "success"
    assert event["args_redacted"]["password"] == "<redacted>"
    assert event["args_redacted"]["vba_code"]["sha256"]
    assert Path(event["args_redacted"]["vba_code"]["artifact"]).is_file()


def test_trace_records_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CST_TRACE_ROOT", str(tmp_path))
    monkeypatch.setenv("CST_TRACE_ID", "unit-error")

    @trace_function
    def failing_tool() -> None:
        raise RuntimeError("expected")

    with pytest.raises(RuntimeError, match="expected"):
        failing_tool()
    event = json.loads(
        (tmp_path / "unit-error" / "trace.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert event["status"] == "error"
    assert event["error"]["type"] == "RuntimeError"


@pytest.mark.parametrize('fail',[False,True])
def test_async_trace_waits_for_actual_outcome(tmp_path,monkeypatch,fail):
    monkeypatch.setenv('CST_TRACE_ROOT',str(tmp_path))
    monkeypatch.setenv('CST_TRACE_ID','awaited')
    trace=tmp_path/'awaited/trace.jsonl'
    async def scenario():
        entered=asyncio.Event();release=asyncio.Event()
        @trace_function
        async def review():
            entered.set();await release.wait()
            if fail: raise RuntimeError('confirmation transport failed')
            return {'status':'awaiting_confirmation'}
        task=asyncio.create_task(review())
        await entered.wait()
        assert not trace.exists(), 'a pending human confirmation is not a completed call'
        release.set()
        if fail:
            with pytest.raises(RuntimeError,match='transport failed'): await task
        else:
            assert await task=={'status':'awaiting_confirmation'}
    asyncio.run(scenario())
    events=[json.loads(line) for line in trace.read_text().splitlines()]
    assert len(events)==1
    assert events[0]['status']==('error' if fail else 'success')
    if not fail: assert events[0]['result_summary']['status']=='awaiting_confirmation'
