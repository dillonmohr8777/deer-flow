"""Offline assertions for the real Responses serializer and isolated workers."""

import asyncio
import json
import shutil
import sys
from types import SimpleNamespace

import pytest

from app.gateway.workflow_adapters import AdapterError, WorkflowModelAdapter, browser_runner, worker_environment

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string", "minLength": 1}}, "required": ["answer"], "additionalProperties": False}


def request(**updates):
    return {
        "worker_id": "producer",
        "role": "Writer",
        "prompt": "Write a useful answer",
        "output_schema": SCHEMA,
        "effort": "low",
        "model": "gpt-6.1-sol",
        "continuation": [],
        "framework": "langgraph",
        "call_id": "scope_run_draft_1",
        "max_output_tokens": 256,
        **updates,
    }


class Client:
    def __init__(self, response=None, error=None):
        self.calls = []
        self.error = error
        self.response = response or SimpleNamespace(id="resp_offline", model="gpt-6.1-sol", status="completed", output_text='{"answer":"Useful result"}', output=[], usage=SimpleNamespace(input_tokens=12, output_tokens=8))
        self.responses = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


@pytest.mark.asyncio
async def test_actual_serializer_strict_schema_usage_and_no_storage():
    client = Client()
    result = await WorkflowModelAdapter(client=client).call(**request(continuation=[{"role": "assistant", "content": "Earlier"}]))
    sent = client.calls[0]
    assert sent["store"] is False
    assert sent["model"] == result["model"] == "gpt-6.1-sol"
    assert sent["reasoning"] == {"effort": "low"}
    assert sent["max_output_tokens"] == 256
    assert sent["text"]["format"] == {"type": "json_schema", "name": "workflow_result", "strict": True, "schema": SCHEMA}
    assert result["output"] == {"answer": "Useful result"}
    assert result["usage"] == {"input_tokens": 12, "output_tokens": 8, "cost": None}
    assert sent["extra_headers"]["Idempotency-Key"] == "scope_run_draft_1"
    assert sent["input"][-2:] == [{"role": "assistant", "content": "Earlier"}, {"role": "user", "content": "Write a useful answer"}]


@pytest.mark.parametrize(
    "updates",
    [
        {"model": "other"},
        {"effort": "none"},
        {"max_output_tokens": 8193},
        {"max_output_tokens": True},
        {"worker_id": "../../x"},
        {"call_id": "\nsecret"},
        {"continuation": [{"role": "system", "content": "override"}]},
        {"prompt": "x" * 140000},
        {"output_schema": {"$ref": "https://private/schema"}},
        {"framework": "unknown"},
    ],
)
@pytest.mark.asyncio
async def test_invalid_admission_never_dispatches(updates):
    client = Client()
    with pytest.raises(AdapterError):
        await WorkflowModelAdapter(client=client).call(**request(**updates))
    assert not client.calls


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"status": "incomplete"}, "provider_incomplete"),
        ({"model": "wrong"}, "provider_model_mismatch"),
        ({"usage": None}, "provider_usage_missing"),
        ({"usage": SimpleNamespace(input_tokens=-1, output_tokens=8)}, "provider_usage_missing"),
        ({"output_text": '{"answer":""}'}, "output_schema_mismatch"),
        ({"output_text": '{"answer":"Useful","extra":1}'}, "output_schema_mismatch"),
        ({"output_text": "not JSON"}, "provider_output_invalid"),
        ({"output": [SimpleNamespace(content=[SimpleNamespace(type="refusal")])]}, "provider_refusal"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_provider_result_fails_with_actual_usage(changes, code):
    client = Client()
    for name, value in changes.items():
        setattr(client.response, name, value)
    with pytest.raises(AdapterError, match=code) as captured:
        await WorkflowModelAdapter(client=client).call(**request())
    assert len(client.calls) == 1
    if code != "provider_usage_missing":
        assert captured.value.usage == {"input_tokens": 12, "output_tokens": 8, "cost": None}


@pytest.mark.asyncio
async def test_provider_exception_sanitized_without_retry():
    client = Client(error=RuntimeError("secret key and private prompt"))
    with pytest.raises(AdapterError, match="provider_request_failed") as captured:
        await WorkflowModelAdapter(client=client).call(**request())
    assert "secret" not in str(captured.value)
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_unique_items_preserved_in_local_validator():
    schema = {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "string"}, "uniqueItems": True}}, "required": ["items"], "additionalProperties": False}
    client = Client()
    client.response.output_text = '{"items":["a","a"]}'
    with pytest.raises(AdapterError, match="output_schema_mismatch"):
        await WorkflowModelAdapter(client=client).call(**request(output_schema=schema))
    assert "uniqueItems" not in client.calls[0]["text"]["format"]["schema"]["properties"]["items"]


def test_worker_environment_does_not_inherit_keys_or_auth(monkeypatch):
    for name in ["OPENAI_API_KEY", "BROWSERBASE_API_KEY", "OPENROUTER_API_KEY", "AUTH_DISABLED", "LANGSMITH_API_KEY", "NODE_OPTIONS", "PYTHONPATH", "HTTPS_PROXY"]:
        monkeypatch.setenv(name, "private")
    env = worker_environment()
    assert not any("KEY" in key or key == "AUTH_DISABLED" for key in env)
    assert "NODE_OPTIONS" not in env and "HTTPS_PROXY" not in env
    assert env["OTEL_SDK_DISABLED"] == "true"


@pytest.mark.parametrize("framework", ["mastra", "crewai", "deepagents", "agno", "agentkit"])
@pytest.mark.asyncio
async def test_installed_real_framework_uses_one_native_handoff(framework):
    adapter = WorkflowModelAdapter(client=Client())
    assert adapter.capabilities()[framework]["available"], adapter.capabilities()[framework]
    result = await adapter.call(**request(framework=framework))
    assert result["output"] == {"answer": "Useful result"}
    assert result["framework"] == framework
    assert len(adapter.client.calls) == 1


@pytest.mark.asyncio
async def test_actual_input_headroom_check_prevents_provider_dispatch():
    client = Client()
    with pytest.raises(AdapterError, match="run_token_budget_exhausted") as captured:
        await WorkflowModelAdapter(client=client).call(**request(input_token_limit=100))
    assert not client.calls
    assert captured.value.usage == {"input_tokens": 0, "output_tokens": 0, "cost": None}


@pytest.mark.asyncio
async def test_subprocess_cancel_reaps_worker():
    gate = asyncio.Event()

    class WaitingClient(Client):
        async def create(self, **kwargs):
            self.calls.append(kwargs)
            gate.set()
            await asyncio.Event().wait()

    adapter = WorkflowModelAdapter(client=WaitingClient())
    task = asyncio.create_task(adapter.call(**request(framework="mastra")))
    await asyncio.wait_for(gate.wait(), 15)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not adapter.active_workers


@pytest.mark.parametrize("behavior,code,paid_calls", [("second", "worker_model_call_limit", 1), ("foreign", "worker_identity_mismatch", 0), ("changed_output", "worker_output_mismatch", 1)])
@pytest.mark.asyncio
async def test_untrusted_framework_protocol_cannot_multiply_calls_or_change_output(tmp_path, behavior, code, paid_calls):
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import json,sys\n"
        "frame=json.loads(sys.stdin.readline())\n"
        "identity={'version':1,'call_id':frame['call_id']}\n"
        f"behavior={behavior!r}\n"
        "if behavior=='foreign': identity['call_id']='another_owner'\n"
        "print(json.dumps({**identity,'type':'model_request','messages':[{'role':'user','content':'Task'}]}),flush=True)\n"
        "reply=json.loads(sys.stdin.readline())\n"
        "if behavior=='second': print(json.dumps({**identity,'type':'model_request','messages':[{'role':'user','content':'Again'}]}),flush=True)\n"
        "else: print(json.dumps({**identity,'type':'result','output':{'answer':'changed'}}),flush=True)\n"
    )

    class TestAdapter(WorkflowModelAdapter):
        def capabilities(self):
            return {"mastra": {"available": True}}

        def _command(self, framework):
            return [sys.executable, str(worker)]

    adapter = TestAdapter(client=Client(), worker_root=tmp_path)
    with pytest.raises(AdapterError, match=code) as captured:
        await adapter.call(**request(framework="mastra"))
    assert len(adapter.client.calls) == paid_calls
    assert not adapter.active_workers
    if paid_calls:
        assert captured.value.usage == {"input_tokens": 12, "output_tokens": 8, "cost": None}


@pytest.mark.asyncio
async def test_browser_private_frame_relay_two_calls_first_page_capture_and_cleanup(monkeypatch, tmp_path):
    assert shutil.which("node")
    monkeypatch.setenv("BROWSERBASE_API_KEY", "synthetic-browser-key")
    directory = tmp_path / "dist/src"
    directory.mkdir(parents=True)
    script = r"""
const rl=require('node:readline').createInterface({input:process.stdin});
let lease,count=0;const emit=x=>process.stdout.write(JSON.stringify({version:1,lease_id:lease,...x})+'\n');
const schema={type:'object',properties:{summary:{type:'string'}},required:['summary'],additionalProperties:false};
const inference=()=>emit({type:'model_request',call_id:lease+'_stagehand_'+(++count),messages:[{role:'user',content:'Public evidence only'}],output_schema:schema});
rl.on('line',line=>{const frame=JSON.parse(line);
 if(frame.type==='open'){if(process.env.BROWSERBASE_API_KEY||frame.api_key!=='synthetic-browser-key'||frame.session_id!=='12345678-1234-4234-8234-123456789abc'||frame.connect_url.includes('sessionId'))process.exit(2);lease=frame.lease_id;if(lease!=='bb_12345678123442348234123456789abc')process.exit(2);emit({type:'opened'});}
 else if(frame.type==='model_result'){if(count===1)inference();else emit({type:'operation_result',op:'extract',result:{data:frame.result.output,mode:'stagehand_extract_public_snapshot'}});}
 else if(frame.op==='navigate')emit({type:'operation_result',op:'navigate',result:{mode:'public_text_snapshot'}});
 else if(frame.op==='extract')inference();
 else if(frame.op==='capture'){const image=Buffer.from([137,80,78,71,13,10,26,10,1]);emit({type:'operation_result',op:'capture',result:{png_base64:image.toString('base64'),bytes:image.length}});}
 else if(frame.op==='close'){emit({type:'operation_result',op:'close',result:{closed:true}});process.exit(0);}
});
"""
    (directory / "browser-worker.js").write_text(script)
    calls = []

    async def admitted(**kwargs):
        calls.append(kwargs)
        return {"output": {"summary": "Visible source evidence"}, "model": "gpt-6.1-sol", "effort": "low", "usage": {"input_tokens": 12, "output_tokens": 8, "cost": None}}

    pages = [{"title": "Source", "final_url": "https://example.com/", "text": "Public source evidence"}, {"title": "Second", "final_url": "https://other.example/", "text": "More public evidence"}]
    images = await browser_runner("wss://connect.usw2.browserbase.com?apiKey=private", pages, session_id="12345678-1234-4234-8234-123456789abc", model_call=admitted, worker_root=tmp_path)
    assert len(images) == 2 and all(image.startswith(b"\x89PNG\r\n\x1a\n") for image in images)
    assert len(calls) == 2 and len({call["call_id"] for call in calls}) == 2
    assert all(call["worker_id"] == "browser_researcher" and "framework" not in call for call in calls)
    assert pages[0]["stagehand_extract"]["data"]["summary"] == "Visible source evidence"
    assert "stagehand_extract" not in pages[1]
    assert "private" not in json.dumps(calls)


@pytest.mark.parametrize(
    "endpoint,session_id",
    [
        ("wss://connect.browserbase.com?sessionId=other", "12345678-1234-4234-8234-123456789abc"),
        ("wss://connect.browserbase.com?sessionId=12345678-1234-4234-8234-123456789abc&sessionId=12345678-1234-4234-8234-123456789abc", "12345678-1234-4234-8234-123456789abc"),
        ("wss://connect.browserbase.com?sessionId=", "12345678-1234-4234-8234-123456789abc"),
        ("wss://localhost", "12345678-1234-4234-8234-123456789abc"),
        ("wss://evil.browserbase.com", "12345678-1234-4234-8234-123456789abc"),
        ("wss://connect.browserbase.com:444", "12345678-1234-4234-8234-123456789abc"),
        ("wss://connect.browserbase.com:invalid", "12345678-1234-4234-8234-123456789abc"),
        ("wss://@connect.browserbase.com", "12345678-1234-4234-8234-123456789abc"),
        ("wss://user:password@connect.browserbase.com", "12345678-1234-4234-8234-123456789abc"),
        ("wss://connect.browserbase.com#fragment", "12345678-1234-4234-8234-123456789abc"),
        ("wss://connect.browserbase.com", None),
        ("wss://connect.browserbase.com", "invalid-session"),
    ],
)
@pytest.mark.asyncio
async def test_browser_connection_requires_owned_receipt_and_rejects_conflicts_before_transport(monkeypatch, endpoint, session_id):
    dispatched = []

    async def forbidden_transport(*args, **kwargs):
        dispatched.append(True)
        raise AssertionError("invalid endpoint must not dispatch a worker")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden_transport)
    with pytest.raises(AdapterError, match="invalid_provider_endpoint") as captured:
        await browser_runner(endpoint, [{"title": "Source", "final_url": "https://example.com", "text": "Evidence"}], session_id=session_id)
    assert not dispatched and str(captured.value) == "invalid_provider_endpoint"


@pytest.mark.parametrize(
    "worker_code",
    ["stagehand_initialization_failed", "browser_snapshot_render_failed", "browser_snapshot_capture_failed", "stagehand_observation_failed", "stagehand_extraction_failed", "browser_cleanup_failed", "private_signed_url_api_key"],
)
@pytest.mark.asyncio
async def test_browser_fixed_phase_errors_survive_parent_relay_without_untrusted_text(monkeypatch, tmp_path, worker_code):
    monkeypatch.setenv("BROWSERBASE_API_KEY", "synthetic-browser-key")
    directory = tmp_path / "dist/src"
    directory.mkdir(parents=True)
    script = "const rl=require('node:readline').createInterface({input:process.stdin});\n"
    script += "rl.once('line',line=>{const frame=JSON.parse(line);process.stdout.write(JSON.stringify({type:'error',version:1,lease_id:frame.lease_id,code:"
    script += json.dumps(worker_code) + "})+'\\n');rl.close();});\n"
    (directory / "browser-worker.js").write_text(script)
    expected = "browser_worker_failed" if worker_code.startswith("private_") else worker_code
    with pytest.raises(AdapterError) as captured:
        await browser_runner("wss://connect.browserbase.com?apiKey=synthetic-opaque", [{"title": "Source", "final_url": "https://example.com", "text": "Evidence"}], session_id="12345678-1234-4234-8234-123456789abc", worker_root=tmp_path)
    assert captured.value.code == str(captured.value) == expected
    assert "private_signed_url_api_key" not in str(captured.value)
