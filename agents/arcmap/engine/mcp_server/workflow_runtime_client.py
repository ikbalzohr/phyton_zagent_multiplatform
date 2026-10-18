from __future__ import annotations

import json
import os
from urllib.parse import urlencode, urlsplit, quote
from .request_context import current
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PermissionError("INTERNAL_CHANNEL_REDIRECT_DENIED")
from urllib.error import HTTPError, URLError


class TunnelWorkflowRuntime:
    def __init__(self, base_url: str, timeout_seconds: float = 10.0):
        self.base_url = str(base_url).rstrip("/")
        target = urlsplit(self.base_url)
        if target.scheme != 'http' or target.hostname not in ('localhost', '127.0.0.1', '127.0.0.3', '::1') or target.username or target.password or target.query or target.fragment:
            raise ValueError('Workflow runtime must use the private loopback channel')
        self.timeout_seconds = max(1.0, float(timeout_seconds))

    @classmethod
    def from_environment(cls):
        explicit = os.environ.get("ZAGENT_WORKFLOW_RUNTIME_URL", "").strip()
        host = os.environ.get("ZAGENT_BIND_HOST", "127.0.0.3").strip()
        port = os.environ.get("ZAGENT_TUNNEL_PORT", "").strip()
        if not explicit and not port:
            raise ValueError("ZAGENT_TUNNEL_PORT must be set for the installation")
        base = explicit or ("http://%s:%s" % (host, port))
        return cls(base)

    def _request(self, method: str, path: str, *, params=None, json_body=None):
        url = self.base_url + path
        if params:
            query = urlencode({
                str(k): str(v)
                for k, v in params.items()
                if v is not None
            })
            if query:
                url += ("&" if "?" in url else "?") + query

        data = None
        token = os.environ.get('ZAGENT_INTERNAL_TOKEN', '')
        ctx = current()
        if len(token.encode('utf-8')) < 32 or not ctx.get('principal_id') or not ctx.get('workspace_id'):
            raise PermissionError('AUTHENTICATED_INTERNAL_CHANNEL_REQUIRED')
        headers = {"Accept": "application/json", 'X-Zagent-Internal-Token': token}
        json_body = dict(json_body or {})
        json_body['execution_context'] = {k: v for k, v in ctx.items() if k not in ('session_id', 'expires_at', 'mcp_receive_epoch', 'mcp_tool_name')}
        if json_body is not None:
            data = json.dumps(
                json_body,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(
            url,
            data=data,
            headers=headers,
            method=method.upper(),
        )
        try:
            with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
            return json.loads(raw or "{}")
        except HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except Exception:
                body = {"error": str(exc)}
            return {
                "ok": False,
                "status": "FAILED",
                "errors": [{
                    "code": "DURABLE_RUNTIME_HTTP_%d" % exc.code,
                    "details": body,
                }],
            }
        except (URLError, OSError, ValueError) as exc:
            return {
                "ok": False,
                "status": "RECOVERY_REQUIRED",
                "errors": [{
                    "code": "DURABLE_RUNTIME_UNAVAILABLE",
                    "message": str(exc),
                }],
            }

    def submit(self, plan, owner, idempotency_key=None, priority=1):
        return self._request(
            "POST",
            "/router/workflows/submit",
            json_body={
                "plan": plan,
                "owner": owner,
                "idempotency_key": idempotency_key or "",
                "priority": int(priority),
            },
        )

    def status(self, run_id, owner_session_id):
        return self._request(
            "POST",
            "/router/workflows/%s/status" % quote(str(run_id), safe=""),
            json_body={},
        )

    def cancel(self, run_id, owner_session_id):
        return self._request(
            "POST",
            "/router/workflows/%s/cancel" % quote(str(run_id), safe=""),
            json_body={"session_id": owner_session_id},
        )

    def resume(self, run_id, owner_session_id, review_decision=None):
        return {'ok': False, 'status': 'BLOCKED', 'errors': [{'code': 'DURABLE_RESUME_NOT_AVAILABLE', 'message': 'Resume requires server-side review authorization; not a caller-supplied decision.'}]}

    def _request_resume_when_supported(self, run_id, owner_session_id, review_decision=None):
        return self._request(
            "POST",
            "/router/workflows/%s/resume" % quote(str(run_id), safe=""),
            json_body={
                "session_id": owner_session_id,
                "review_decision": review_decision,
            },
        )

    def report(self, run_id, owner_session_id):
        return self._request(
            "POST",
            "/router/workflows/%s/report" % quote(str(run_id), safe=""),
            json_body={},
        )
