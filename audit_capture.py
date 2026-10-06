"""Opt-in loopback HTTP/SSE/WebSocket relay; writes only reasoning audit metadata.

No credentials are loaded, no client configuration is changed, and no probes
are sent. Authentication headers from a caller are forwarded only in memory.
Compressed HTTP responses are relayed without claiming complete audit fields.
"""
from __future__ import annotations

from datetime import datetime, timezone
import http.client
import ipaddress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import socket
from urllib.parse import urlsplit
from urllib.request import getproxies, proxy_bypass
import uuid


HOP_HEADERS = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
               'te', 'trailer', 'transfer-encoding', 'upgrade', 'host'}
MAX_BODY = 32 * 1024 * 1024
MAX_EVENT = 1024 * 1024


def upstream_connection(upstream, timeout):
    """Use the caller's HTTP system proxy; keep loopback and NO_PROXY direct."""
    host = upstream.hostname
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.lower() == 'localhost'
    connection_type = http.client.HTTPSConnection if upstream.scheme == 'https' else http.client.HTTPConnection
    proxy_url = None if loopback or proxy_bypass(host) else getproxies().get(upstream.scheme)
    if not proxy_url:
        return connection_type(host, upstream.port, timeout=timeout), False
    proxy = urlsplit(proxy_url)
    if (proxy.scheme != 'http' or not proxy.hostname or proxy.username or proxy.password or
            proxy.query or proxy.fragment or proxy.path not in ('', '/')):
        raise ValueError('采集器支持无认证的 HTTP 系统代理；当前代理类型或认证方式不受支持。')
    conn = connection_type(proxy.hostname, proxy.port or 80, timeout=timeout)
    if upstream.scheme == 'https':
        conn.set_tunnel(host, upstream.port or 443)
        return conn, False
    return conn, True


def _reasoning(obj: dict) -> dict:
    result = {}
    nested = obj.get('reasoning')
    if isinstance(nested, dict) and isinstance(nested.get('effort'), str):
        result['reasoning'] = {'effort': nested['effort'][:128]}
    if isinstance(obj.get('reasoning_effort'), str):
        result['reasoning_effort'] = obj['reasoning_effort'][:128]
    return result


def request_metadata(obj: dict) -> dict:
    result = _reasoning(obj)
    if isinstance(obj.get('model'), str):
        result['model'] = obj['model'][:128]
    if isinstance(obj.get('stream'), bool):
        result['stream'] = obj['stream']
    else:
        result['stream'] = False
    if isinstance(obj.get('input'), list):
        updates = [dict(type='configuration_update', **_reasoning(item)) for item in obj['input']
                   if isinstance(item, dict) and item.get('type') == 'configuration_update']
        if updates:
            result['input'] = updates
    return result


def response_metadata(obj: dict) -> dict:
    result = _reasoning(obj)
    for key in ('id', 'model'):
        if isinstance(obj.get(key), str):
            result[key] = obj[key][:128]
    usage = obj.get('usage')
    if isinstance(usage, dict):
        safe = {}
        output = usage.get('output_tokens')
        if isinstance(output, int) and not isinstance(output, bool) and output >= 0:
            safe['output_tokens'] = output
        details = usage.get('output_tokens_details')
        reasoning = details.get('reasoning_tokens') if isinstance(details, dict) else None
        if isinstance(reasoning, int) and not isinstance(reasoning, bool) and reasoning >= 0:
            safe['output_tokens_details'] = {'reasoning_tokens': reasoning}
        if safe:
            result['usage'] = safe
    return result


class _SSE:
    """Incrementally decode bounded SSE frames without storing output text."""
    def __init__(self, callback):
        self.callback = callback
        self.pending = b''
        self.data = []
        self.size = 0
        self.skipping = False

    def feed(self, chunk: bytes):
        self.pending += chunk
        while b'\n' in self.pending:
            line, self.pending = self.pending.split(b'\n', 1)
            line = line.rstrip(b'\r')
            if not line:
                if self.data and not self.skipping:
                    try:
                        obj = json.loads(b'\n'.join(self.data))
                        if isinstance(obj, dict):
                            self.callback(obj)
                    except (ValueError, UnicodeError):
                        pass
                self.data, self.size, self.skipping = [], 0, False
            elif line.startswith(b'data:') and not self.skipping:
                self.size += len(line)
                if self.size > MAX_EVENT:
                    self.data, self.skipping = [], True
                else:
                    self.data.append(line[5:].lstrip(b' '))
        if len(self.pending) > MAX_EVENT:
            self.pending, self.data, self.skipping = b'', [], True


class _Writer:
    def __init__(self, path: Path, client: str, profile='', lock=None):
        self.path, self.client = path, client
        self.profile = profile
        self.source_id = 'capture-' + uuid.uuid4().hex
        self.lock = lock or threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8'):
            pass

    def for_headers(self, headers):
        if self.client != 'Auto':
            return self
        origin = (headers.get('originator', '') + ' ' + headers.get('User-Agent', '')).lower()
        client = 'Desktop' if 'codex_desktop' in origin or 'codex desktop' in origin else (
            'CLI' if 'codex_cli_rs' in origin or 'codex-cli' in origin else 'Other')
        return _ClientWriter(self, client)

    def emit(self, request_id: str, kind: str, payload: dict, *, transport='http', client=None):
        obj = dict(schema_version=1, source_id=self.source_id, request_id=request_id, attempt_id='1',
                   timestamp=datetime.now(timezone.utc).isoformat(), protocol='responses',
                   observation_boundary='client_to_provider', client=client or self.client, event_type=kind)
        obj['transport'] = transport
        if self.profile:
            obj['profile'] = self.profile
        obj['request' if kind == 'request_sent' else 'response'] = payload
        line = json.dumps(obj, ensure_ascii=False, allow_nan=False) + '\n'
        with self.lock, self.path.open('a', encoding='utf-8') as stream:
            stream.write(line)


class _ClientWriter:
    def __init__(self, writer, client):
        self.writer, self.client = writer, client

    def emit(self, request_id, kind, payload, **kwargs):
        self.writer.emit(request_id, kind, payload, client=self.client, **kwargs)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def handle(self):
        try:
            super().handle()
        except ConnectionError:
            self.close_connection = True

    def log_message(self, *args):
        pass

    def _error(self, status: int, message: str):
        self.close_connection = True
        body = json.dumps({'error': message}).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._relay()

    def do_POST(self):
        self._relay()

    def _relay(self):
        if self.headers.get('Upgrade', '').lower() == 'websocket':
            from websocket_capture import relay_websocket
            relay_websocket(self)
            return
        route = urlsplit(self.path)
        if route.scheme or route.netloc or not route.path.startswith('/v1/'):
            self._error(400, 'Expected a /v1/ API path.')
            return
        if self.headers.get('Transfer-Encoding'):
            self._error(411, 'Chunked request bodies are not supported; supply Content-Length.')
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0 or length > MAX_BODY:
                raise ValueError
        except ValueError:
            self._error(413, 'Request body limit is 32 MiB.')
            return
        self.connection.settimeout(30)
        try:
            body = self.rfile.read(length) if length else None
        except OSError:
            self._error(408, 'Request body read timed out or failed.')
            return
        if body is not None and len(body) != length:
            self._error(400, 'Incomplete request body.')
            return
        auditing = self.command == 'POST' and route.path == '/v1/responses'
        request_id = uuid.uuid4().hex
        sent_headers, terminal = False, False
        last_response = {}
        writer = self.server.audit_writer.for_headers(self.headers)
        upstream = self.server.upstream
        conn = None
        try:
            if auditing:
                compressed_request = self.headers.get('Content-Encoding', 'identity').lower() not in ('', 'identity')
                if compressed_request:
                    # Preserve an HTTP fallback even when this Python cannot decode
                    # the client's compression. An absent outbound grade stays unknown.
                    metadata = {}
                else:
                    try:
                        payload = json.loads(body or b'{}')
                    except (ValueError, UnicodeError):
                        self._error(400, 'Responses requests must contain a JSON object.')
                        return
                    if not isinstance(payload, dict):
                        self._error(400, 'Responses requests must contain a JSON object.')
                        return
                    metadata = request_metadata(payload)
                writer.emit(request_id, 'request_sent', metadata)
            conn, absolute_target = upstream_connection(upstream, self.server.upstream_timeout)
            excluded = HOP_HEADERS | {v.strip().lower() for v in self.headers.get('Connection', '').split(',')}
            headers = {key: value for key, value in self.headers.items() if key.lower() not in excluded}
            # Body bytes, model, effort and authentication are forwarded unchanged.
            headers['Accept-Encoding'] = 'identity'
            path = upstream.path.rstrip('/') + route.path[3:]
            if route.query:
                path += '?' + route.query
            if absolute_target:
                path = upstream.scheme + '://' + upstream.netloc + path
            conn.request(self.command, path, body=body, headers=headers)
            response = conn.getresponse()
            is_sse = 'text/event-stream' in response.getheader('Content-Type', '').lower()
            compressed = response.getheader('Content-Encoding', 'identity').lower() not in ('', 'identity')
            # Compressed bytes are relayed as-is but cannot provide audit fields.
            capturing = auditing and not compressed

            def on_event(obj):
                nonlocal terminal, last_response
                kind = obj.get('type')
                if kind not in ('response.created', 'response.completed', 'response.failed', 'response.incomplete'):
                    return
                value = obj.get('response')
                if not isinstance(value, dict):
                    return
                last_response = response_metadata(value)
                writer.emit(request_id, kind.replace('.', '_'), last_response)
                terminal |= kind != 'response.created'

            decoder = _SSE(on_event)
            excluded = HOP_HEADERS | {v.strip().lower() for v in response.getheader('Connection', '').split(',')}
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in excluded and key.lower() != 'content-length':
                    self.send_header(key, value)
            self.send_header('Transfer-Encoding', 'chunked')
            self.end_headers()
            sent_headers = True
            if auditing and not 200 <= response.status < 300:
                writer.emit(request_id, 'response_failed', {})
                terminal = True
            collected = bytearray()
            too_large = False
            while True:
                chunk = response.read1(16384)
                if not chunk:
                    break
                if capturing and not terminal:
                    # Some official Codex streams omit Content-Type. Inspect the
                    # bounded frame prefix and keep JSON fallback for nonstreams.
                    if not is_sse:
                        prefix = (bytes(collected[:64]) + chunk[:64]).lstrip()
                        if prefix.startswith((b'data:', b'event:', b':')):
                            is_sse = True
                            collected.clear()
                    decoder.feed(chunk)
                    if not is_sse and len(collected) + len(chunk) <= MAX_BODY:
                        collected.extend(chunk)
                    elif not is_sse:
                        collected.clear()
                        capturing, too_large = False, True
                self.wfile.write(f'{len(chunk):X}\r\n'.encode() + chunk + b'\r\n')
                self.wfile.flush()
            if auditing and not terminal:
                if capturing and not is_sse and not too_large:
                    try:
                        value = json.loads(collected)
                    except (ValueError, UnicodeError):
                        value = {}
                    if isinstance(value, dict):
                        last_response = response_metadata(value)
                    state = value.get('status') if isinstance(value, dict) else None
                    kind = ('response_failed' if state == 'failed' else 'response_incomplete' if state in
                            ('incomplete', 'queued', 'in_progress') or not last_response.get('id') else 'response_completed')
                    writer.emit(request_id, kind, last_response)
                else:
                    writer.emit(request_id, 'response_incomplete', last_response)
                terminal = True
            self.wfile.write(b'0\r\n\r\n')
            self.wfile.flush()
        except (OSError, http.client.HTTPException, ValueError):
            if auditing and not terminal:
                try:
                    writer.emit(request_id, 'response_incomplete' if sent_headers else 'response_failed', last_response)
                except OSError:
                    pass
            if not sent_headers:
                self._error(502, 'Upstream or audit writer failed; no automatic retry was sent.')
            self.close_connection = True
        finally:
            if conn is not None:
                conn.close()


class _CaptureServer(ThreadingHTTPServer):
    def __init__(self, *args):
        self.ws_lock = threading.Lock()
        self.ws_sockets = set()
        self.ws_closing = False
        super().__init__(*args)

    def register_websocket(self, sockets):
        with self.ws_lock:
            if self.ws_closing:
                raise OSError('Capture server is closing.')
            self.ws_sockets.update(sockets)

    def unregister_websocket(self, sockets):
        with self.ws_lock:
            self.ws_sockets.difference_update(sockets)

    def server_close(self):
        with self.ws_lock:
            self.ws_closing = True
            for sock in self.ws_sockets:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        super().server_close()


def create_capture_server(upstream_url: str, audit_path: Path, *, port=8766, client='Other', timeout=1800, profile='', log_lock=None):
    upstream = urlsplit(upstream_url)
    if (upstream.scheme not in ('http', 'https') or not upstream.hostname or upstream.username or
            upstream.password or upstream.query or upstream.fragment):
        raise ValueError('上游必须是无凭据、无查询参数的 HTTP(S) API base URL。')
    try:
        upstream.port
    except ValueError as exc:
        raise ValueError('上游端口无效。') from exc
    writer = _Writer(audit_path, client, profile, log_lock)
    server = _CaptureServer(('127.0.0.1', port), _Handler)
    server.daemon_threads = True
    if upstream.hostname in ('127.0.0.1', 'localhost', '::1') and upstream.port == server.server_port:
        server.server_close()
        raise ValueError('上游地址不能指向采集入口自身。')
    server.upstream, server.audit_writer, server.upstream_timeout = upstream, writer, timeout
    return server


def run_capture(upstream_url: str, audit_path: Path, port: int, client: str, timeout: float, profile='') -> int:
    server = create_capture_server(upstream_url, audit_path, port=port, client=client, timeout=timeout, profile=profile)
    print(f'HTTP/SSE/WebSocket 审计采集： http://127.0.0.1:{server.server_port}/v1\n'
          f'日志：{audit_path.resolve()}\n仅手动配置的客户端会经过此入口。Ctrl+C 停止。', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
