"""RFC 6455 byte relay with bounded, metadata-only Responses observation."""
from __future__ import annotations

import base64
from collections import deque
from dataclasses import dataclass, field
from hashlib import sha1
import http.client
import json
import socket
import threading
import uuid
from urllib.parse import urlsplit

from audit_capture import HOP_HEADERS, MAX_BODY, request_metadata, response_metadata, upstream_connection


@dataclass
class _Pending:
    request_id: str | None
    lane: str | None
    response_id: str | None = None
    last: dict = field(default_factory=dict)


class ResponsesObserver:
    """Named lanes are FIFO; response IDs keep interleaved lanes independent."""
    def __init__(self, writer):
        self.writer = writer
        self.lanes = {}
        self.responses = {}
        self.finished = deque(maxlen=256)
        self.lock = threading.Lock()
        self.closed = False

    def emit(self, pending, kind, payload):
        if pending.request_id:
            self.writer.emit(pending.request_id, kind, payload, transport='websocket')

    def client(self, obj):
        if obj.get('type') != 'response.create':
            return
        lane = obj.get('stream_id')
        if lane is not None and (not isinstance(lane, str) or len(lane) > 128):
            return
        with self.lock:
            if self.closed:
                return
            # Keep even prewarm requests in the FIFO, but omit them from inference audits.
            pending = _Pending(None if obj.get('generate') is False else uuid.uuid4().hex, lane)
            if sum(len(queue) for queue in self.lanes.values()) >= 256:
                self._finish_all('response_incomplete')
            self.lanes.setdefault(lane, deque()).append(pending)
            metadata = request_metadata(obj)
            metadata['stream'] = True
            self.emit(pending, 'request_sent', metadata)

    def _remove(self, pending):
        queue = self.lanes.get(pending.lane)
        if queue and queue[0] is pending:
            queue.popleft()
            if not queue:
                self.lanes.pop(pending.lane, None)
        if pending.response_id:
            self.responses.pop(pending.response_id, None)
            self.finished.append(pending.response_id)

    def server(self, obj):
        kind = obj.get('type')
        if kind not in ('response.created', 'response.completed', 'response.failed', 'response.incomplete', 'error'):
            return
        lane = obj.get('stream_id')
        if lane is not None and not isinstance(lane, str):
            return
        value = obj.get('response')
        value = value if isinstance(value, dict) else {}
        response_id = value.get('id')
        if not isinstance(response_id, str):
            response_id = None
        with self.lock:
            if self.closed:
                return
            if response_id in self.finished:
                return
            pending = self.responses.get(response_id) if response_id else None
            if pending and lane is not None and lane != pending.lane:
                return  # Conflicting identity is never guessed onto a different request.
            if pending is None:
                queue = self.lanes.get(lane)
                if not queue:
                    if kind == 'error' and lane is None:
                        self._finish_all('response_failed')
                    return
                pending = queue[0]
                if pending.response_id and pending.response_id != response_id and kind != 'error':
                    return
                if response_id:
                    pending.response_id = response_id
                    self.responses[response_id] = pending
            if kind == 'error':
                self.emit(pending, 'response_failed', pending.last)
                self._remove(pending)
                return
            if not response_id:
                return
            pending.last = response_metadata(value)
            self.emit(pending, kind.replace('.', '_'), pending.last)
            if kind != 'response.created':
                self._remove(pending)

    def _finish_all(self, kind):
        for queue in list(self.lanes.values()):
            for pending in queue:
                self.emit(pending, kind, pending.last)
        self.lanes.clear()
        self.responses.clear()

    def close(self):
        with self.lock:
            self.closed = True
            self._finish_all('response_incomplete')


def _exact(reader, length):
    data = bytearray()
    while len(data) < length:
        chunk = reader.read(length - len(data))
        if not chunk:
            raise EOFError
        data.extend(chunk)
    return bytes(data)


def relay_frames(reader, send, callback, *, client):
    """Forward original frames, observing text only; control frames can interleave."""
    message, text, fragmented, oversized = bytearray(), False, False, False
    while True:
        header = _exact(reader, 2)
        first, second = header
        opcode, final, masked = first & 15, bool(first & 128), bool(second & 128)
        if first & 0x70 or masked != client or opcode not in (0, 1, 2, 8, 9, 10):
            raise ValueError('Invalid uncompressed WebSocket frame.')
        size = second & 127
        if size in (126, 127):
            extended = _exact(reader, 2 if size == 126 else 8)
            header += extended
            size = int.from_bytes(extended, 'big')
            if size >= 1 << 63:
                raise ValueError('Invalid WebSocket length.')
        control = opcode >= 8
        if control and (not final or size > 125):
            raise ValueError('Invalid WebSocket control frame.')
        if not control:
            if opcode == 0 and not fragmented or opcode in (1, 2) and fragmented:
                raise ValueError('Invalid WebSocket fragmentation.')
            if opcode in (1, 2):
                message, text, oversized = bytearray(), opcode == 1, False
            fragmented = not final
        mask = _exact(reader, 4) if masked else b''
        send(header + mask)
        offset = 0
        while offset < size:
            read = getattr(reader, 'read1', reader.read)
            chunk = read(min(16384, size - offset))
            if not chunk:
                raise EOFError
            if not control and text and not oversized:
                if len(message) + len(chunk) > MAX_BODY:
                    message.clear()
                    oversized = True
                else:
                    message.extend(bytes(value ^ mask[(offset+i) % 4] for i, value in enumerate(chunk))
                                   if mask else chunk)
            offset += len(chunk)
            if offset == size and not control and final and text and not oversized:
                try:
                    obj = json.loads(message)
                except (ValueError, UnicodeError):
                    obj = None
                if isinstance(obj, dict):
                    # Observe before forwarding the last bytes: upstream cannot race
                    # response.created ahead of the corresponding request_sent.
                    callback(obj)
                message.clear()
            send(chunk)
        if opcode == 8:
            return


def relay_websocket(handler):
    route = urlsplit(handler.path)
    key = handler.headers.get('Sec-WebSocket-Key', '')
    try:
        valid_key = len(base64.b64decode(key, validate=True)) == 16
    except (ValueError, UnicodeError):
        valid_key = False
    if (handler.command != 'GET' or route.scheme or route.netloc or route.path != '/v1/responses'
            or handler.headers.get('Sec-WebSocket-Version') != '13' or not valid_key
            or 'upgrade' not in {v.strip().lower() for v in handler.headers.get('Connection', '').split(',')}
            or handler.headers.get('Content-Length', '0') != '0' or handler.headers.get('Transfer-Encoding')):
        handler._error(400, 'Invalid WebSocket handshake for /v1/responses.')
        return
    conn = response = None
    observer = ResponsesObserver(handler.server.audit_writer.for_headers(handler.headers))
    upgraded, sockets = False, ()
    handler.close_connection = True
    try:
        upstream = handler.server.upstream
        conn, absolute = upstream_connection(upstream, handler.server.upstream_timeout)
        excluded = HOP_HEADERS | {'sec-websocket-extensions'} | {
            v.strip().lower() for v in handler.headers.get('Connection', '').split(',')}
        headers = {k:v for k,v in handler.headers.items() if k.lower() not in excluded}
        headers.update(Connection='Upgrade', Upgrade='websocket')
        # Decline optional compression on both hops; message/body bytes stay identical.
        path = upstream.path.rstrip('/') + '/responses'
        if route.query:
            path += '?' + route.query
        if absolute:
            path = upstream.scheme + '://' + upstream.netloc + path
        conn.request('GET', path, headers=headers)
        response = conn.getresponse()
        accept = base64.b64encode(sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        if (response.status != 101 or response.getheader('Upgrade', '').lower() != 'websocket'
                or 'upgrade' not in {v.strip().lower() for v in response.getheader('Connection', '').split(',')}
                or response.getheader('Sec-WebSocket-Accept') != accept
                or response.getheader('Sec-WebSocket-Extensions') or conn.sock is None):
            handler._error(response.status if response.status >= 400 else 502, 'Upstream WebSocket upgrade rejected.')
            return
        protocol = response.getheader('Sec-WebSocket-Protocol')
        offered = {v.strip() for v in handler.headers.get('Sec-WebSocket-Protocol', '').split(',')}
        if protocol and protocol not in offered:
            handler._error(502, 'Upstream selected an unoffered WebSocket protocol.')
            return
        sockets = (handler.connection, conn.sock)
        handler.server.register_websocket(sockets)
        handler.connection.settimeout(handler.server.upstream_timeout)
        handler.send_response(101)
        for k,v in response.getheaders():
            if k.lower() not in HOP_HEADERS | {'content-length', 'sec-websocket-extensions'}:
                handler.send_header(k,v)
        handler.send_header('Connection', 'Upgrade')
        handler.send_header('Upgrade', 'websocket')
        handler.end_headers()
        handler.wfile.flush()
        upgraded = True
        done = threading.Event()
        failures = []

        def pump(reader, send, callback, client):
            try:
                relay_frames(reader, send, callback, client=client)
            except (EOFError, OSError, ValueError):
                failures.append(True)
            finally:
                done.set()

        # Keep both existing buffered readers, including bytes following the HTTP
        # handshake. HTTPResponse.read() cannot be used for a 101 (zero HTTP body).
        threads = [threading.Thread(target=pump, args=(handler.rfile, conn.sock.sendall, observer.client, True), daemon=True),
                   threading.Thread(target=pump, args=(response.fp, handler.connection.sendall, observer.server, False), daemon=True)]
        for thread in threads:
            thread.start()
        done.wait()
        if not failures:
            for thread in threads:
                thread.join(1)  # Give the close reply time to pass through.
        observer.close()
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        for thread in threads:
            thread.join(2)
    except (OSError, ValueError, http.client.HTTPException):
        if not upgraded:
            handler._error(502, 'WebSocket relay failed; no automatic retry was sent.')
    finally:
        observer.close()
        if sockets:
            handler.server.unregister_websocket(sockets)
        if response:
            response.close()
        if conn:
            conn.close()
