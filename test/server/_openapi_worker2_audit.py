# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import traceback

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_COLLAPSED_OPENAPI_PATH = _PROJECT_ROOT / "tmp" / "collapsed_openapi_api_routes.json"
DEFAULT_TIMEOUT = httpx.Timeout(connect=10, read=60, write=60, pool=10)


Validator = Any


@dataclass(frozen=True)
class AuditCase:
    name: str
    method: str
    path: str
    baseline_path: str | None = None
    params: dict[str, Any] | None = None
    json_body: Any = None
    data: Any = None
    files: Any = None
    headers: dict[str, str] | None = None
    expect_status: tuple[int, ...] = (200,)
    expect_keys: tuple[str, ...] | None = None
    expect_type: type[Any] | tuple[type[Any], ...] | None = None
    validator: Validator | None = None
    note: str = ""


@dataclass(frozen=True)
class AuditResult:
    name: str
    method: str
    path: str
    status: int | None
    ok: bool
    msg: str
    body_preview: str
    note: str = ""


def _short(value: Any, limit: int = 200) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    if len(text) > limit:
        return text[:limit] + f"...(+{len(text) - limit})"
    return text


def _load_response_body(response: httpx.Response) -> Any:
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            return response.json()
        except Exception:
            return response.text
    return response.text


def _service_list_validator(body: Any, _response: httpx.Response) -> bool | str:
    if not isinstance(body, list):
        return f"expected list, got {type(body).__name__}"
    kinds = {str(item.get('kind') or '') for item in body if isinstance(item, dict)}
    expected = {"completion", "embedding", "s2t", "t2s"}
    if not expected.issubset(kinds):
        return f"missing kinds: {sorted(expected - kinds)}"
    return True


def _dict_with_list_key(key: str) -> Validator:
    def _validator(body: Any, _response: httpx.Response) -> bool | str:
        if not isinstance(body, dict):
            return f"expected dict, got {type(body).__name__}"
        if not isinstance(body.get(key), list):
            return f"missing list key `{key}`"
        return True

    return _validator


def _roots_and_shells_validator(body: Any, _response: httpx.Response) -> bool | str:
    if not isinstance(body, dict):
        return f"expected dict, got {type(body).__name__}"
    if not isinstance(body.get("roots"), list):
        return "roots missing"
    if not isinstance(body.get("available_shells"), list):
        return "available_shells missing"
    return True


DEFAULT_BATCH1_CASES: tuple[AuditCase, ...] = (
    AuditCase("system root", "GET", "/_internal/admin/api/system", expect_keys=("timestamp", "cpu_avg", "cpu_cores", "mem_used", "mem_total")),
    AuditCase("system cpu", "GET", "/_internal/admin/api/system/cpu"),
    AuditCase("system extended", "GET", "/_internal/admin/api/system/extended"),
    AuditCase("system gpu", "GET", "/_internal/admin/api/system/gpu"),
    AuditCase("system ports", "GET", "/_internal/admin/api/system/ports"),
    AuditCase("system processes", "GET", "/_internal/admin/api/system/processes", params={"limit": 5}),
    AuditCase("system last infos", "GET", "/_internal/admin/api/system_last_infos"),
    AuditCase("system tools config", "GET", "/_internal/admin/api/system/tools/config", validator=_roots_and_shells_validator),
    AuditCase("system files list root", "GET", "/_internal/admin/api/system/files/list", params={"path": "."}),
    AuditCase("system files list tmp", "GET", "/_internal/admin/api/system/files/list", params={"path": "tmp"}),
    AuditCase("system files text", "GET", "/_internal/admin/api/system/files/text", params={"path": "tmp/collapsed_openapi_api_routes.json"}, expect_status=(200, 400, 413)),
    AuditCase("system files raw", "GET", "/_internal/admin/api/system/files/raw", params={"path": "tmp/collapsed_openapi_api_routes.json"}, expect_status=(200, 400)),
    AuditCase("server config", "GET", "/api/server/config", expect_type=dict),
    AuditCase("backend runtime", "GET", "/_internal/admin/api/backend/runtime", expect_type=dict),
    AuditCase("backend settings", "GET", "/_internal/admin/api/backend/settings", expect_type=dict),
    AuditCase("backend control noop invalid", "POST", "/_internal/admin/api/backend/control", json_body={"action": "noop"}, expect_status=(400, 422)),
    AuditCase("ai services list", "GET", "/api/ai/services", validator=_service_list_validator),
    AuditCase("ai service completion", "GET", "/api/ai/services/completion", baseline_path="/api/ai/services/{kind}", expect_keys=("kind", "instances", "clients")),
    AuditCase("ai service embedding", "GET", "/api/ai/services/embedding", baseline_path="/api/ai/services/{kind}", expect_keys=("kind", "instances", "clients")),
    AuditCase("ai service s2t", "GET", "/api/ai/services/s2t", baseline_path="/api/ai/services/{kind}", expect_keys=("kind", "instances", "clients")),
    AuditCase("ai service t2s", "GET", "/api/ai/services/t2s", baseline_path="/api/ai/services/{kind}", expect_keys=("kind", "instances", "clients")),
    AuditCase("ai has env thinkthinksyn", "GET", "/api/ai/clients/thinkthinksyn/has-env-key", baseline_path="/api/ai/clients/{provider}/has-env-key", expect_keys=("has_env_key",)),
    AuditCase("ai has env openrouter", "GET", "/api/ai/clients/openrouter/has-env-key", baseline_path="/api/ai/clients/{provider}/has-env-key", expect_keys=("has_env_key",)),
    AuditCase("ai completion status", "GET", "/api/ai/completion-status", expect_keys=("client_count", "healthy_count")),
    AuditCase("ai languages", "GET", "/api/ai/languages"),
    AuditCase("ai embedding cache stats", "GET", "/api/ai/embedding/cache-stats"),
    AuditCase("ai embedding cache clear", "POST", "/api/ai/embedding/cache-clear", json_body={}, expect_status=(200, 422)),
    AuditCase("storage kv clients", "GET", "/_internal/admin/api/storage/kv/clients", validator=_dict_with_list_key("clients")),
    AuditCase("storage kv config", "GET", "/_internal/admin/api/storage/kv/config", expect_type=dict),
    AuditCase("storage kv summary", "GET", "/_internal/admin/api/storage/kv/summary", expect_status=(200, 400, 422)),
    AuditCase("storage orm clients", "GET", "/_internal/admin/api/storage/orm/clients", validator=_dict_with_list_key("clients")),
    AuditCase("storage orm config", "GET", "/_internal/admin/api/storage/orm/config", expect_type=dict),
    AuditCase("storage orm collections", "GET", "/_internal/admin/api/storage/orm/collections", expect_status=(200, 400, 422)),
    AuditCase("storage object clients", "GET", "/_internal/admin/api/storage/object/clients", validator=_dict_with_list_key("clients")),
    AuditCase("storage object config", "GET", "/_internal/admin/api/storage/object/config", expect_type=dict),
    AuditCase("storage vector clients", "GET", "/_internal/admin/api/storage/vector/clients", validator=_dict_with_list_key("clients")),
    AuditCase("storage vector config", "GET", "/_internal/admin/api/storage/vector/config", expect_type=dict),
    AuditCase("storage vector collections", "GET", "/_internal/admin/api/storage/vector/collections", expect_status=(200, 400, 422)),
    AuditCase("logs overview", "GET", "/_internal/admin/api/logs/overview"),
    AuditCase("logs meta", "GET", "/_internal/admin/api/logs/meta"),
    AuditCase("logs config", "GET", "/_internal/admin/api/logs/config"),
    AuditCase("logs query", "GET", "/_internal/admin/api/logs", params={"limit": 5}, expect_status=(200, 400, 422)),
    AuditCase("logs service stats", "GET", "/_internal/admin/api/logs/service/stats", expect_status=(200, 400, 422)),
    AuditCase("rooms list", "GET", "/_internal/admin/api/rooms", params={"page": 1, "page_size": 10}, expect_status=(200, 400, 422)),
    AuditCase("rooms missing", "GET", "/_internal/admin/api/rooms/__nope__", baseline_path="/_internal/admin/api/rooms/{room_id}", expect_status=(200, 400, 404, 422)),
    AuditCase("ai services overview", "GET", "/_internal/admin/ai-services/overview", expect_status=(200, 400, 422)),
    AuditCase("ai services settings", "GET", "/_internal/admin/ai-services/settings", expect_status=(200, 400, 422)),
    AuditCase("files upload unauth", "POST", "/api/files/upload", expect_status=(401, 422)),
    AuditCase("files get unauth", "POST", "/api/files/get", json_body={"file_id": "x"}, expect_status=(401, 403, 422)),
    AuditCase("files delete unauth", "POST", "/api/files/delete", json_body={"file_id": "x"}, expect_status=(401, 403, 422)),
    AuditCase("temp upload token", "POST", "/api/ai/upload_temp_file", json_body={"file_size": 1024, "mime": "text/plain"}, expect_status=(200, 400, 422)),
)


DEFAULT_BATCH2_CASES: tuple[AuditCase, ...] = (
    AuditCase("ui translate", "GET", "/api/ui_translate", params={"keys": "ok,cancel", "lang": "zh-cn"}, expect_keys=("translations",)),
    AuditCase("ui translate all", "GET", "/api/ui_translate/all", expect_keys=("translations",)),
    AuditCase("ai services settings apply invalid payload", "POST", "/_internal/admin/ai-services/settings/apply", json_body={}, expect_status=(400, 422, 500)),
    AuditCase("ai services probe missing completion", "POST", "/_internal/admin/ai-services/probe/completion/__nope__", baseline_path="/_internal/admin/ai-services/probe/{service_type}/{service_key}", json_body={}, expect_status=(404, 400, 422, 500)),
)


DEFAULT_BATCH3_CASES: tuple[AuditCase, ...] = ()


DEFAULT_BATCH4_CASES: tuple[AuditCase, ...] = (
    AuditCase("ai service missing instance", "GET", "/api/ai/services/completion/instances/__nope__", baseline_path="/api/ai/services/{kind}/instances/{instance_key}", expect_status=(404,)),
    AuditCase("ai service missing client", "GET", "/api/ai/services/completion/clients/__nope__", baseline_path="/api/ai/services/{kind}/clients/{client_key}", expect_status=(404,)),
    AuditCase("ai thinkthinksyn models endpoint", "POST", "/api/ai/clients/thinkthinksyn/list-models", json_body={}, expect_status=(200, 400, 401, 422, 500, 502)),
    AuditCase("ai openrouter models endpoint", "POST", "/api/ai/clients/openrouter/list-models", json_body={}, expect_status=(200, 400, 401, 422, 500, 502)),
    AuditCase("logs service logs", "GET", "/_internal/admin/api/logs/service/logs", params={"limit": 5}, expect_status=(200,)),
    AuditCase("logs service timeline", "GET", "/_internal/admin/api/logs/service/timeline", params={"hours": 1, "bucket_minutes": 60}, expect_status=(200,)),
)


DEFAULT_BATCH5_CASES: tuple[AuditCase, ...] = (
    AuditCase("ai complete invalid payload", "POST", "/api/ai/complete", json_body={}, expect_status=(422,)),
    AuditCase("ai thinkthinksyn invalid payload", "POST", "/api/ai/test_thinkthinksyn_complete", json_body={}, expect_status=(422,)),
    AuditCase("ai openrouter invalid payload", "POST", "/api/ai/test_openrouter_complete", json_body={}, expect_status=(422,)),
    AuditCase("ai translate invalid payload", "POST", "/api/ai/translate", json_body={}, expect_status=(422,)),
    AuditCase("ai detect language invalid payload", "POST", "/api/ai/detect-language", json_body={}, expect_status=(422,)),
    AuditCase("ai ocr missing file", "POST", "/api/ai/ocr", expect_status=(422,)),
    AuditCase("ai asr missing file", "POST", "/api/ai/asr", expect_status=(422,)),
    AuditCase("ai summarize invalid payload", "POST", "/api/ai/summarize", json_body={}, expect_status=(422,)),
    AuditCase("ai s2t missing file", "POST", "/api/ai/s2t", expect_status=(422,)),
    AuditCase("ai t2s invalid payload", "POST", "/api/ai/t2s", json_body={}, expect_status=(422,)),
    AuditCase("ai t2s stream invalid payload", "POST", "/api/ai/t2s/stream", json_body={}, expect_status=(422,)),
    AuditCase("ai embedding invalid payload", "POST", "/api/ai/embedding", json_body={}, expect_status=(400, 422, 500)),
    AuditCase("ai embedding rerank invalid payload", "POST", "/api/ai/embedding/rerank", json_body={}, expect_status=(422,)),
    AuditCase("ai embedding chunking invalid payload", "POST", "/api/ai/embedding/chunking", json_body={}, expect_status=(422,)),
    AuditCase("ai embedding diversity invalid payload", "POST", "/api/ai/embedding/diversity", json_body={}, expect_status=(422,)),
    AuditCase("ai transcript missing file", "POST", "/api/ai/transcript", expect_status=(422,)),
    AuditCase("ai rerank invalid payload", "POST", "/api/ai/rerank", json_body={}, expect_status=(422,)),
    AuditCase("ai services settings apply invalid payload", "POST", "/_internal/admin/ai-services/settings/apply", json_body={}, expect_status=(400, 422, 500)),
    AuditCase("ai services probe missing completion", "POST", "/_internal/admin/ai-services/probe/completion/__nope__", baseline_path="/_internal/admin/ai-services/probe/{service_type}/{service_key}", json_body={}, expect_status=(404, 400, 422, 500)),
)


DEFAULT_BATCH6_CASES: tuple[AuditCase, ...] = (
    AuditCase("logs before future", "DELETE", "/_internal/admin/api/logs/before/2030-01-01T00:00:00", baseline_path="/_internal/admin/api/logs/before/{timestamp:path}", expect_status=(200, 404)),
    AuditCase("test audio missing", "GET", "/api/test-audio/__missing__.mp3", baseline_path="/api/test-audio/{filename}", expect_status=(404,)),
    AuditCase("system process invalid pid", "GET", "/_internal/admin/api/system/processes/0", baseline_path="/_internal/admin/api/system/processes/{pid}", expect_status=(400, 403, 404)),
    AuditCase("system process terminate missing", "POST", "/_internal/admin/api/system/processes/999999/terminate", baseline_path="/_internal/admin/api/system/processes/{pid}/terminate", expect_status=(404,)),
    AuditCase("system process kill missing", "POST", "/_internal/admin/api/system/processes/999999/kill", baseline_path="/_internal/admin/api/system/processes/{pid}/kill", expect_status=(404,)),
    AuditCase("rooms create invalid empty", "POST", "/api/rooms/create", json_body={}, expect_status=(422,)),
    AuditCase("rooms join invalid empty", "POST", "/api/rooms/join", json_body={}, expect_status=(422,)),
)


DEFAULT_BATCH7_CASES: tuple[AuditCase, ...] = (
    AuditCase("kv keys basic", "GET", "/_internal/admin/api/storage/kv/keys", expect_status=(200,)),
    AuditCase("kv item missing query", "GET", "/_internal/admin/api/storage/kv/item", expect_status=(422,)),
    AuditCase("kv put missing query", "PUT", "/_internal/admin/api/storage/kv/item", json_body={}, expect_status=(422,)),
    AuditCase("kv ttl missing query", "PATCH", "/_internal/admin/api/storage/kv/item/ttl", json_body={}, expect_status=(422,)),
    AuditCase("kv delete missing query", "DELETE", "/_internal/admin/api/storage/kv/item", expect_status=(422,)),
    AuditCase("kv delete by prefix dryrun", "POST", "/_internal/admin/api/storage/kv/delete-by-prefix", json_body={"prefix": "__nope__", "dry_run": True, "limit": 1}, expect_status=(200,)),
    AuditCase("kv delete many missing key", "POST", "/_internal/admin/api/storage/kv/delete-many", json_body={"keys": ["__nope__"]}, expect_status=(200,)),
    AuditCase("kv bulk ttl missing key", "PATCH", "/_internal/admin/api/storage/kv/items/ttl", json_body={"keys": ["__nope__"], "expire_seconds": 1}, expect_status=(200,)),
    AuditCase("kv cleanup", "POST", "/_internal/admin/api/storage/kv/cleanup", expect_status=(200,)),
    AuditCase("object items basic", "GET", "/_internal/admin/api/storage/object/items", expect_status=(200,)),
    AuditCase("object folder invalid", "POST", "/_internal/admin/api/storage/object/folder", json_body={}, expect_status=(422,)),
    AuditCase("object upload missing file", "POST", "/_internal/admin/api/storage/object/upload", expect_status=(422,)),
    AuditCase("object meta missing", "GET", "/_internal/admin/api/storage/object/meta", params={"path": "__nope__/missing.txt"}, expect_status=(404,)),
    AuditCase("object content missing", "GET", "/_internal/admin/api/storage/object/content", params={"path": "__nope__/missing.txt"}, expect_status=(404,)),
    AuditCase("object office preview missing", "GET", "/_internal/admin/api/storage/object/office-preview", params={"path": "__nope__/missing.docx"}, expect_status=(404,)),
    AuditCase("object office preview pdf missing", "GET", "/_internal/admin/api/storage/object/office-preview/pdf", params={"path": "__nope__/missing.pptx"}, expect_status=(404,)),
    AuditCase("object office preview thumb missing", "GET", "/_internal/admin/api/storage/object/office-preview/thumb", params={"path": "__nope__/missing.pptx", "page": 1}, expect_status=(404,)),
    AuditCase("object write invalid base64", "PUT", "/_internal/admin/api/storage/object/content", params={"path": "__nope__/new.bin"}, json_body={"mode": "base64", "value": "***", "content_type": "application/octet-stream"}, expect_status=(400,)),
    AuditCase("object metadata missing", "PATCH", "/_internal/admin/api/storage/object/metadata", params={"path": "__nope__/missing.txt"}, json_body={"metadata": {"x": 1}, "merge": True}, expect_status=(404,)),
    AuditCase("object copy invalid", "POST", "/_internal/admin/api/storage/object/copy", json_body={}, expect_status=(422,)),
    AuditCase("object move invalid", "POST", "/_internal/admin/api/storage/object/move", json_body={}, expect_status=(422,)),
    AuditCase("object delete missing query", "DELETE", "/_internal/admin/api/storage/object/item", expect_status=(422,)),
    AuditCase("object delete many empty", "POST", "/_internal/admin/api/storage/object/delete-many", json_body={"paths": []}, expect_status=(200, 422)),
    AuditCase("object expire missing", "PATCH", "/_internal/admin/api/storage/object/expire", params={"path": "__nope__/missing.txt"}, json_body={"expire_seconds": 1}, expect_status=(404,)),
    AuditCase("object cleanup", "POST", "/_internal/admin/api/storage/object/cleanup", expect_status=(200,)),
    AuditCase("orm schema missing query", "GET", "/_internal/admin/api/storage/orm/schema", expect_status=(422,)),
    AuditCase("orm indexes missing query", "GET", "/_internal/admin/api/storage/orm/indexes", expect_status=(422,)),
    AuditCase("orm document missing query", "GET", "/_internal/admin/api/storage/orm/document", expect_status=(422,)),
    AuditCase("orm create index invalid", "POST", "/_internal/admin/api/storage/orm/index", json_body={}, expect_status=(422,)),
    AuditCase("orm drop index missing query", "DELETE", "/_internal/admin/api/storage/orm/index", expect_status=(422,)),
    AuditCase("orm query invalid", "POST", "/_internal/admin/api/storage/orm/query", json_body={}, expect_status=(422,)),
    AuditCase("orm collection invalid", "POST", "/_internal/admin/api/storage/orm/collection", json_body={}, expect_status=(422,)),
    AuditCase("orm upsert invalid", "PUT", "/_internal/admin/api/storage/orm/document", json_body={}, expect_status=(422,)),
    AuditCase("orm delete missing query", "DELETE", "/_internal/admin/api/storage/orm/document", expect_status=(422,)),
    AuditCase("orm delete many invalid", "POST", "/_internal/admin/api/storage/orm/delete-many", json_body={}, expect_status=(422,)),
    AuditCase("orm expire invalid", "PATCH", "/_internal/admin/api/storage/orm/expire", json_body={}, expect_status=(422,)),
    AuditCase("orm drop collection missing query", "DELETE", "/_internal/admin/api/storage/orm/collection", expect_status=(422,)),
    AuditCase("orm cleanup", "POST", "/_internal/admin/api/storage/orm/cleanup", expect_status=(200,)),
    AuditCase("vector collection missing query", "GET", "/_internal/admin/api/storage/vector/collection", expect_status=(422,)),
    AuditCase("vector schema missing query", "GET", "/_internal/admin/api/storage/vector/schema", expect_status=(422,)),
    AuditCase("vector document missing query", "GET", "/_internal/admin/api/storage/vector/document", expect_status=(422,)),
    AuditCase("vector create invalid", "POST", "/_internal/admin/api/storage/vector/collection", json_body={"collection": "__invalid__", "vector_fields": []}, expect_status=(400, 422)),
    AuditCase("vector browse invalid", "POST", "/_internal/admin/api/storage/vector/browse", json_body={}, expect_status=(422,)),
    AuditCase("vector upsert invalid", "PUT", "/_internal/admin/api/storage/vector/document", json_body={}, expect_status=(422,)),
    AuditCase("vector search invalid", "POST", "/_internal/admin/api/storage/vector/search", json_body={}, expect_status=(422,)),
    AuditCase("vector delete many invalid", "POST", "/_internal/admin/api/storage/vector/delete-many", json_body={}, expect_status=(422,)),
    AuditCase("vector delete missing query", "DELETE", "/_internal/admin/api/storage/vector/document", expect_status=(422,)),
    AuditCase("vector drop collection missing query", "DELETE", "/_internal/admin/api/storage/vector/collection", expect_status=(422,)),
    AuditCase("vector load missing query", "POST", "/_internal/admin/api/storage/vector/collection/load", expect_status=(422,)),
    AuditCase("vector offload missing query", "POST", "/_internal/admin/api/storage/vector/collection/offload", expect_status=(422,)),
    AuditCase("vector expire invalid", "PATCH", "/_internal/admin/api/storage/vector/expire", json_body={}, expect_status=(422,)),
    AuditCase("vector cleanup", "POST", "/_internal/admin/api/storage/vector/cleanup", expect_status=(200,)),
    AuditCase("vector cleanup", "POST", "/_internal/admin/api/storage/vector/cleanup", expect_status=(200,)),
)


DEFAULT_BATCH8_CASES: tuple[AuditCase, ...] = (
    AuditCase("logs delete all", "DELETE", "/_internal/admin/api/logs", expect_status=(200, 404)),
    AuditCase("backend settings invalid empty", "POST", "/_internal/admin/api/backend/settings", json_body={}, expect_status=(422,)),
    AuditCase("rooms delete missing", "DELETE", "/_internal/admin/api/rooms/__nope__", baseline_path="/_internal/admin/api/rooms/{room_id}", expect_status=(404,)),
    AuditCase("system files delete missing", "DELETE", "/_internal/admin/api/system/files/item", params={"path": "tmp/__openapi_missing__.txt"}, expect_status=(404,)),
    AuditCase("system files download missing", "GET", "/_internal/admin/api/system/files/download", params={"path": "tmp/__openapi_missing__.txt"}, expect_status=(404,)),
    AuditCase("system files office preview missing", "GET", "/_internal/admin/api/system/files/office-preview", params={"path": "tmp/__openapi_missing__.docx"}, expect_status=(404,)),
    AuditCase("system files office preview pdf missing", "GET", "/_internal/admin/api/system/files/office-preview/pdf", params={"path": "tmp/__openapi_missing__.pptx"}, expect_status=(404,)),
    AuditCase("system files office preview thumb missing", "GET", "/_internal/admin/api/system/files/office-preview/thumb", params={"path": "tmp/__openapi_missing__.pptx", "page": 1}, expect_status=(404,)),
    AuditCase("system files mkdir invalid missing form", "POST", "/_internal/admin/api/system/files/mkdir", expect_status=(422,)),
    AuditCase("system files upload invalid missing file", "POST", "/_internal/admin/api/system/files/upload", data={"root": "workspace", "path": "tmp"}, expect_status=(422,)),
    AuditCase("system files write invalid empty", "PUT", "/_internal/admin/api/system/files/text", json_body={}, expect_status=(400, 422)),
)


def collapsed_route_keys() -> set[tuple[str, str]]:
    payload = json.loads(_COLLAPSED_OPENAPI_PATH.read_text(encoding="utf-8"))
    keys: set[tuple[str, str]] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        method = str(item.get("method") or "").upper()
        for path in item.get("paths") or []:
            keys.add((method, str(path)))
    return keys


def run_audit_case(client: httpx.Client, case: AuditCase) -> AuditResult:
    status: int | None = None
    body_preview = ""
    try:
        response = client.request(
            case.method,
            case.path,
            params=case.params,
            json=case.json_body,
            data=case.data,
            files=case.files,
            headers=case.headers,
        )
        status = response.status_code
        body = _load_response_body(response)
        body_preview = _short(body)
        if response.status_code not in case.expect_status:
            return AuditResult(case.name, case.method, case.path, status, False, f"unexpected status {status}, want {case.expect_status}", body_preview, case.note)
        if case.expect_type is not None and not isinstance(body, case.expect_type):
            return AuditResult(case.name, case.method, case.path, status, False, f"body type {type(body).__name__} mismatch", body_preview, case.note)
        if case.expect_keys is not None:
            if not isinstance(body, dict):
                return AuditResult(case.name, case.method, case.path, status, False, "body is not an object", body_preview, case.note)
            missing = [key for key in case.expect_keys if key not in body]
            if missing:
                return AuditResult(case.name, case.method, case.path, status, False, f"missing keys: {missing}", body_preview, case.note)
        if case.validator is not None:
            verdict = case.validator(body, response)
            if verdict is not True:
                return AuditResult(case.name, case.method, case.path, status, False, f"validator fail: {verdict}", body_preview, case.note)
        return AuditResult(case.name, case.method, case.path, status, True, "ok", body_preview, case.note)
    except Exception as exc:
        body_preview = traceback.format_exc(limit=2)
        return AuditResult(case.name, case.method, case.path, status, False, f"EXC {exc}", body_preview, case.note)


def run_audit_cases(base_url: str, cases: tuple[AuditCase, ...] = DEFAULT_BATCH1_CASES) -> list[AuditResult]:
    with httpx.Client(base_url=base_url, timeout=DEFAULT_TIMEOUT, follow_redirects=False, proxy=None) as client:
        return [run_audit_case(client, case) for case in cases]


def format_report(results: list[AuditResult]) -> str:
    lines: list[str] = []
    for result in results:
        flag = "OK " if result.ok else "FAIL"
        status = "---" if result.status is None else f"{result.status:>3}"
        lines.append(f"[{flag}] {status} {result.method:<5} {result.path:<60} {result.msg}")
        if result.note:
            lines.append(f"        note: {result.note}")
        if not result.ok:
            lines.append(f"        body: {result.body_preview}")
    return "\n".join(lines) + ("\n" if lines else "")


def write_report(report_path: Path, results: list[AuditResult]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(format_report(results), encoding="utf-8")
