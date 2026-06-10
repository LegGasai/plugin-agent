from __future__ import annotations

import ipaddress
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from plugin_agent_sdk import Plugin


DEFAULT_CONFIG = {
    "security": {
        "allow_raw_requests": False,
        "allowed_schemes": ["https"],
        "allowed_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"],
        "allowed_hosts": [],
        "allow_private_networks": False,
        "allow_redirects": False,
        "default_timeout_seconds": 15,
        "max_timeout_seconds": 30,
        "max_response_bytes": 65536,
    },
    "default_headers": {},
    "default_secret_headers": {},
    "endpoints": {},
}

FORBIDDEN_CALL_HEADERS = {
    "authorization",
    "cookie",
    "set-cookie",
    "host",
    "content-length",
    "transfer-encoding",
    "proxy-authorization",
}
PLACEHOLDER_PATTERN = re.compile(r"^\{([A-Za-z0-9_.-]+)\}$")
TEMPLATE_PATTERN = re.compile(r"\{([A-Za-z0-9_.-]+)\}")


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HttpRequestToolPlugin(Plugin):
    def start(self, kernel: Any) -> None:
        super().start(kernel)
        if not self._security().get("allow_raw_requests"):
            self.resource_specs = [resource for resource in self.resource_specs if resource.id != "http.raw_request"]

    def invoke(self, capability: str, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if capability == "tool.http_endpoint_request":
            return {"result": self._invoke_endpoint(payload)}
        if capability == "tool.http_raw_request":
            return {"result": self._invoke_raw(payload)}
        return super().invoke(capability, payload, context)

    def _invoke_endpoint(self, payload: dict[str, Any]) -> dict[str, Any]:
        endpoint_id = payload["endpoint_id"]
        endpoint = self._config().get("endpoints", {}).get(endpoint_id)
        if not isinstance(endpoint, dict):
            return self._error("endpoint_not_found", f"HTTP endpoint is not configured: {endpoint_id}", endpoint_id=endpoint_id)

        params = payload.get("params") or {}
        if not isinstance(params, dict):
            return self._error("invalid_params", "params must be an object", endpoint_id=endpoint_id)

        try:
            url = self._render_url(endpoint["url_template"], params)
            query = self._render_template(endpoint.get("query_template") or {}, params)
            query.update(payload.get("query") or {})
            method = str(endpoint.get("method", "GET")).upper()
            headers = self._configured_headers(endpoint, payload.get("headers") or {})
            body = self._render_template(endpoint.get("body_template"), params) if "body_template" in endpoint else None
        except KeyError as exc:
            return self._error("missing_param", f"missing template parameter: {exc.args[0]}", endpoint_id=endpoint_id)
        except ValueError as exc:
            return self._error("header_not_allowed", str(exc), endpoint_id=endpoint_id)

        return self._perform_request(
            method=method,
            url=url,
            query=query,
            headers=headers,
            body_json=body,
            body_text=None,
            timeout_seconds=payload.get("timeout_seconds") or endpoint.get("timeout_seconds"),
            endpoint_id=endpoint_id,
        )

    def _invoke_raw(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._security().get("allow_raw_requests"):
            return self._error("raw_requests_disabled", "HTTP raw requests are disabled by plugin config")
        try:
            headers = self._call_headers(payload.get("headers") or {}, allowed_names=None)
        except ValueError as exc:
            return self._error("header_not_allowed", str(exc))
        return self._perform_request(
            method=str(payload["method"]).upper(),
            url=payload["url"],
            query=payload.get("query") or {},
            headers=headers,
            body_json=payload.get("body_json"),
            body_text=payload.get("body_text"),
            timeout_seconds=payload.get("timeout_seconds"),
            endpoint_id=None,
        )

    def _perform_request(
        self,
        method: str,
        url: str,
        query: dict[str, Any],
        headers: dict[str, str],
        body_json: Any,
        body_text: str | None,
        timeout_seconds: float | None,
        endpoint_id: str | None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        validation_error = self._validate_request_target(method, url)
        if validation_error:
            validation_error["endpoint_id"] = endpoint_id or validation_error.get("endpoint_id")
            validation_error["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            return validation_error

        if body_json is not None and body_text is not None:
            return self._error("ambiguous_body", "body_json and body_text cannot both be set", endpoint_id=endpoint_id)

        url = self._with_query(url, query)
        data = None
        request_headers = dict(headers)
        if body_json is not None:
            data = json.dumps(body_json, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        elif body_text is not None:
            data = body_text.encode("utf-8")

        timeout = self._timeout(timeout_seconds)
        max_response_bytes = int(self._security().get("max_response_bytes", 65536))
        opener = urllib.request.build_opener() if self._security().get("allow_redirects") else urllib.request.build_opener(NoRedirectHandler)
        request = urllib.request.Request(url, data=data, headers=request_headers, method=method)

        try:
            with opener.open(request, timeout=timeout) as response:
                return self._response_result(response, started, max_response_bytes, endpoint_id)
        except urllib.error.HTTPError as exc:
            return self._response_result(exc, started, max_response_bytes, endpoint_id)
        except Exception as exc:
            return self._error(
                "request_failed",
                str(exc),
                endpoint_id=endpoint_id,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )

    def _response_result(self, response: Any, started: float, max_response_bytes: int, endpoint_id: str | None) -> dict[str, Any]:
        raw = response.read(max_response_bytes + 1)
        truncated = len(raw) > max_response_bytes
        raw = raw[:max_response_bytes]
        headers = {key: value for key, value in response.headers.items()}
        text = raw.decode(self._response_charset(headers), errors="replace")
        body_json = None
        if text:
            try:
                body_json = json.loads(text)
            except json.JSONDecodeError:
                body_json = None
        status_code = int(getattr(response, "status", getattr(response, "code", 0)) or 0)
        result = {
            "ok": 200 <= status_code < 400,
            "status_code": status_code,
            "headers": headers,
            "body_text": text,
            "body_json": body_json,
            "truncated": truncated,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "error": None,
        }
        if endpoint_id:
            result["endpoint_id"] = endpoint_id
        if not result["ok"]:
            result["error"] = {"code": "http_error", "message": f"HTTP request returned status {status_code}"}
        return result

    def _validate_request_target(self, method: str, url: str) -> dict[str, Any] | None:
        security = self._security()
        if method not in {item.upper() for item in security.get("allowed_methods", [])}:
            return self._error("method_not_allowed", f"HTTP method is not allowed: {method}")

        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in set(security.get("allowed_schemes", [])):
            return self._error("scheme_not_allowed", f"URL scheme is not allowed: {parsed.scheme}")
        if not parsed.hostname:
            return self._error("invalid_url", "URL host is required")
        if not self._host_allowed(parsed.hostname, security.get("allowed_hosts", [])):
            return self._error("host_not_allowed", f"URL host is not allowed: {parsed.hostname}")
        if not security.get("allow_private_networks") and self._host_resolves_to_private_network(parsed.hostname, parsed.port):
            return self._error("private_network_not_allowed", f"URL host resolves to a private or local address: {parsed.hostname}")
        return None

    def _configured_headers(self, endpoint: dict[str, Any], extra_headers: dict[str, Any]) -> dict[str, str]:
        headers = {}
        headers.update(self._fixed_headers(self._config().get("default_headers") or {}))
        headers.update(self._fixed_headers(endpoint.get("headers") or {}))
        headers.update(self._fixed_headers(self._config().get("default_secret_headers") or {}, allow_sensitive=True))
        headers.update(self._fixed_headers(endpoint.get("secret_headers") or {}, allow_sensitive=True))
        if extra_headers:
            if not endpoint.get("allow_extra_headers"):
                raise ValueError("extra headers are not allowed for this endpoint")
            headers.update(self._call_headers(extra_headers, allowed_names=set(endpoint.get("allowed_extra_header_names") or [])))
        return headers

    def _fixed_headers(self, headers: dict[str, Any], allow_sensitive: bool = False) -> dict[str, str]:
        clean = {}
        for name, value in headers.items():
            self._validate_header_name(name)
            if not allow_sensitive and name.lower() in FORBIDDEN_CALL_HEADERS:
                raise ValueError(f"sensitive header must be configured in secret_headers: {name}")
            clean[name] = str(value)
        return clean

    def _call_headers(self, headers: dict[str, Any], allowed_names: set[str] | None) -> dict[str, str]:
        allowed_lower = {name.lower() for name in allowed_names} if allowed_names is not None else None
        clean = {}
        for name, value in headers.items():
            self._validate_header_name(name)
            lower_name = name.lower()
            if lower_name in FORBIDDEN_CALL_HEADERS:
                raise ValueError(f"call-time header is not allowed: {name}")
            if allowed_lower is not None and lower_name not in allowed_lower:
                raise ValueError(f"call-time header is not whitelisted for this endpoint: {name}")
            clean[name] = str(value)
        return clean

    def _validate_header_name(self, name: str) -> None:
        if not isinstance(name, str) or not name or any(char in name for char in "\r\n:"):
            raise ValueError(f"invalid header name: {name}")

    def _host_allowed(self, hostname: str, allowed_hosts: list[str]) -> bool:
        hostname = hostname.lower().rstrip(".")
        for allowed in allowed_hosts:
            allowed = str(allowed).lower().rstrip(".")
            if allowed.startswith("*.") and hostname.endswith(allowed[1:]) and hostname != allowed[2:]:
                return True
            if hostname == allowed:
                return True
        return False

    def _host_resolves_to_private_network(self, hostname: str, port: int | None) -> bool:
        try:
            infos = socket.getaddrinfo(hostname, port or 443, type=socket.SOCK_STREAM)
        except socket.gaierror:
            return True
        for info in infos:
            address = info[4][0]
            try:
                ip = ipaddress.ip_address(address)
            except ValueError:
                return True
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
                return True
        return False

    def _render_url(self, template: str, params: dict[str, Any]) -> str:
        return TEMPLATE_PATTERN.sub(lambda match: urllib.parse.quote(str(self._param(params, match.group(1))), safe=""), template)

    def _render_template(self, value: Any, params: dict[str, Any]) -> Any:
        if isinstance(value, dict):
            return {key: self._render_template(child, params) for key, child in value.items()}
        if isinstance(value, list):
            return [self._render_template(child, params) for child in value]
        if isinstance(value, str):
            full_match = PLACEHOLDER_PATTERN.match(value)
            if full_match:
                return self._param(params, full_match.group(1))
            return TEMPLATE_PATTERN.sub(lambda match: str(self._param(params, match.group(1))), value)
        return value

    def _param(self, params: dict[str, Any], key: str) -> Any:
        target: Any = params
        for part in key.split("."):
            if not isinstance(target, dict) or part not in target:
                raise KeyError(key)
            target = target[part]
        return target

    def _with_query(self, url: str, query: dict[str, Any]) -> str:
        if not query:
            return url
        parsed = urllib.parse.urlparse(url)
        current = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        current.extend((key, value) for key, value in query.items() if value is not None)
        return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(current, doseq=True)))

    def _timeout(self, requested: float | None) -> float:
        security = self._security()
        timeout = float(requested or security.get("default_timeout_seconds", 15))
        return max(1.0, min(timeout, float(security.get("max_timeout_seconds", 30))))

    def _response_charset(self, headers: dict[str, str]) -> str:
        content_type = headers.get("Content-Type") or headers.get("content-type") or ""
        for part in content_type.split(";"):
            part = part.strip()
            if part.lower().startswith("charset="):
                return part.split("=", 1)[1].strip() or "utf-8"
        return "utf-8"

    def _security(self) -> dict[str, Any]:
        return self._config().get("security", {})

    def _config(self) -> dict[str, Any]:
        return self._deep_merge(DEFAULT_CONFIG, self.config)

    def _deep_merge(self, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        result = dict(base)
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def _error(self, code: str, message: str, endpoint_id: str | None = None, elapsed_ms: int = 0) -> dict[str, Any]:
        result = {
            "ok": False,
            "status_code": None,
            "headers": {},
            "body_text": "",
            "body_json": None,
            "truncated": False,
            "elapsed_ms": elapsed_ms,
            "error": {"code": code, "message": message},
        }
        if endpoint_id:
            result["endpoint_id"] = endpoint_id
        return result
