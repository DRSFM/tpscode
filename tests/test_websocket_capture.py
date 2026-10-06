"""Real socket checks: the relay must preserve frames and separate response lanes."""
import base64
from hashlib import sha1
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest

from audit_capture import create_capture_server
from reasoning_audit import AuditMonitor


def frame(payload, opcode=1, *, masked=False, final=True):
    payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    size = len(payload)
    header = bytes([(0x80 if final else 0) | opcode, (0x80 if masked else 0) | min(size, 126)])
    if size >= 65536:
        header = header[:1] + bytes([(0x80 if masked else 0) | 127]) + struct.pack('!Q', size)
    elif size >= 126:
        header += struct.pack('!H', size)
    if masked:
        mask = b'abcd'
        return header + mask + bytes(value ^ mask[i % 4] for i, value in enumerate(payload))
    return header + payload


def exact(reader, length):
    result = bytearray()
    while len(result) < length:
        chunk = reader.read(length - len(result))
        if not chunk:
            raise EOFError
        result.extend(chunk)
    return bytes(result)


def receive(reader):
    header = exact(reader, 2)
    size = header[1] & 127
    if size in (126, 127):
        extra = exact(reader, 2 if size == 126 else 8)
        header += extra
        size = int.from_bytes(extra, 'big')
    mask = exact(reader, 4) if header[1] & 128 else b''
    payload = exact(reader, size)
    raw = header + mask + payload
    if mask:
        payload = bytes(value ^ mask[i % 4] for i, value in enumerate(payload))
    return header[0] & 15, payload, raw, bool(header[0] & 128)


class WSUpstream(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.headers_seen = dict(self.headers)
        self.server.path_seen = self.path
        key = self.headers['Sec-WebSocket-Key']
        accept = base64.b64encode(sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        self.send_response(101)
        self.send_header('Upgrade', 'websocket')
        self.send_header('Connection', 'Upgrade')
        self.send_header('Sec-WebSocket-Accept', 'invalid' if self.server.mode == 'bad_accept' else accept)
        self.end_headers()
        self.close_connection = True
        try:
            requests, pieces = [], bytearray()
            target = 2 if self.server.mode in ('parallel', 'warmup', 'fifo') else 1
            while len(requests) < target:
                opcode, payload, raw, final = receive(self.rfile)
                self.server.frames.append(raw)
                if opcode == 9:
                    self.wfile.write(frame(payload, 10))
                    continue
                pieces.extend(payload)
                if final:
                    requests.append(json.loads(pieces))
                    pieces.clear()
            if self.server.mode == 'error':
                self.wfile.write(frame({'type':'error', 'stream_id':requests[0].get('stream_id'),
                                       'error':{'message':'PRIVATE ERROR'}}))
                return
            for index in reversed(range(len(requests))):
                request = requests[index]
                response = {'id':f'resp_{index}', 'model':request['model'], 'reasoning':{'effort':'high'}}
                event = dict(type='response.created', response=response)
                if 'stream_id' in request:
                    event['stream_id'] = request['stream_id']
                if self.server.mode == 'fifo':
                    break
                encoded = json.dumps(event).encode()
                self.wfile.write(frame(encoded[:19], final=False) + frame(b'ping', 9) + frame(encoded[19:], 0))
            self.wfile.flush()
            self.server.created.set()
            if self.server.mode == 'disconnect':
                return
            self.server.gate.wait(3)
            order = range(len(requests)) if self.server.mode == 'fifo' else reversed(range(len(requests)))
            for index in order:
                request = requests[index]
                response = {'id':f'resp_{index}', 'model':request['model'], 'reasoning':{'effort':'low'},
                            'output':[{'text':'PRIVATE OUTPUT'}],
                            'usage':{'output_tokens_details':{'reasoning_tokens':index}}}
                extra = {'stream_id':request['stream_id']} if 'stream_id' in request else {}
                if self.server.mode == 'fifo':
                    self.wfile.write(frame(dict(type='response.created', response=response, **extra)))
                self.wfile.write(frame(dict(type='response.completed', response=response, **extra)))
            self.wfile.write(frame(b'\x03\xe8', 8))
            self.wfile.flush()
        except (EOFError, OSError, ValueError):
            pass


class WebSocketCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'audit.jsonl'
        self.upstream = ThreadingHTTPServer(('127.0.0.1', 0), WSUpstream)
        self.upstream.mode = 'single'
        self.upstream.frames = []
        self.upstream.created, self.upstream.gate = threading.Event(), threading.Event()
        self.proxy = create_capture_server(f'http://127.0.0.1:{self.upstream.server_port}/backend', self.path, port=0)
        self.connections = []
        for server in (self.upstream, self.proxy):
            threading.Thread(target=server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.upstream.gate.set()
        for conn, reader in self.connections:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            reader.close()
            conn.close()
        for server in (self.proxy, self.upstream):
            server.shutdown()
            server.server_close()
        self.temp.cleanup()

    def connect(self, early=b''):
        conn = socket.create_connection(('127.0.0.1', self.proxy.server_port), timeout=5)
        reader = conn.makefile('rb')
        self.connections.append((conn, reader))
        handshake = ('GET /v1/responses?test=1 HTTP/1.1\r\nHost: localhost\r\n'
                     'Upgrade: websocket\r\nConnection: Upgrade\r\n'
                     'Sec-WebSocket-Version: 13\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n'
                     'Sec-WebSocket-Extensions: permessage-deflate\r\nAuthorization: Bearer PRIVATE KEY\r\n\r\n').encode()
        conn.sendall(handshake + early)
        status = reader.readline()
        headers = bytearray()
        while True:
            line = reader.readline()
            if line in (b'\r\n', b''):
                break
            headers.extend(line)
        return conn, reader, status, bytes(headers)

    def request(self, **extra):
        return dict(dict(type='response.create', model='test-model', reasoning={'effort':'xhigh'},
                         input='PRIVATE INPUT'), **extra)

    def drain(self, reader):
        result = bytearray()
        while True:
            try:
                opcode, payload, _, _ = receive(reader)
            except EOFError:
                break
            result.extend(payload)
            if opcode == 8:
                break
        return bytes(result)

    def test_buffered_handshake_fragment_ping_and_private_data_are_preserved(self):
        body = json.dumps(self.request()).encode()
        raw = frame(body[:17], masked=True, final=False) + frame(b'hello', 9, masked=True) + frame(body[17:], 0, masked=True)
        _, reader, status, headers = self.connect(raw)
        self.assertIn(b'101', status)
        self.assertNotIn(b'Extensions', headers)
        self.assertTrue(self.upstream.created.wait(3))
        # Read the first streamed frame before allowing the final response.
        opcode, payload, _, _ = receive(reader)
        self.assertEqual(opcode, 10)
        self.assertEqual(payload, b'hello')
        self.upstream.gate.set()
        self.assertIn(b'PRIVATE OUTPUT', self.drain(reader))
        self.assertEqual(b''.join(self.upstream.frames), raw)
        self.assertEqual(self.upstream.path_seen, '/backend/responses?test=1')
        self.assertEqual(self.upstream.headers_seen['Authorization'], 'Bearer PRIVATE KEY')
        self.assertNotIn('Sec-WebSocket-Extensions', self.upstream.headers_seen)
        row = AuditMonitor([self.path]).refresh()[0]
        self.assertEqual((row.first_effort, row.final_effort, row.reasoning_tokens), ('high', 'low', 0))
        self.assertEqual(row.audit_status, 'lowered')
        self.assertTrue(row.stream)
        self.assertNotIn('PRIVATE', self.path.read_text())

    def test_parallel_streams_and_fifo_requests_do_not_cross_associate(self):
        for mode in ('parallel', 'fifo'):
            with self.subTest(mode=mode):
                self.upstream.mode = mode
                self.upstream.gate.set()
                conn, reader, status, _ = self.connect()
                self.assertIn(b'101', status)
                first = self.request(stream_id='left', model='model-left')
                second = self.request(stream_id='right' if mode == 'parallel' else 'left', model='model-right')
                conn.sendall(frame(first, masked=True) + frame(second, masked=True))
                self.drain(reader)
                rows = AuditMonitor([self.path]).refresh()
                self.assertTrue(all(row.model == row.returned_model and row.audit_status == 'lowered' for row in rows))
                self.assertEqual(len(rows), 2 if mode == 'parallel' else 4)

    def test_prewarm_is_excluded_but_its_response_does_not_attach_to_real_request(self):
        self.upstream.mode = 'warmup'
        self.upstream.gate.set()
        conn, reader, status, _ = self.connect()
        self.assertIn(b'101', status)
        conn.sendall(frame(self.request(generate=False, stream_id='warm'), masked=True) +
                     frame(self.request(stream_id='real'), masked=True))
        self.drain(reader)
        rows = AuditMonitor([self.path]).refresh()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].response_id, rows[0].reasoning_tokens), ('resp_1', 1))

    def test_error_disconnect_and_bad_handshake_are_not_completed(self):
        for mode, expected in (('error', 'failed'), ('disconnect', 'incomplete'), ('bad_accept', None)):
            self.upstream.mode = mode
            conn, reader, status, _ = self.connect()
            if mode == 'bad_accept':
                self.assertIn(b'502', status)
                continue
            self.assertIn(b'101', status)
            conn.sendall(frame(self.request(), masked=True))
            self.drain(reader)
            self.assertEqual(AuditMonitor([self.path]).refresh()[0].request_state, expected)

    def test_64_bit_frame_length_preserves_large_request_and_captures_only_metadata(self):
        self.upstream.gate.set()
        raw = frame(self.request(input='PRIVATE ' + 'x' * 70000), masked=True)
        conn, reader, status, _ = self.connect()
        self.assertIn(b'101', status)
        conn.sendall(raw)
        self.drain(reader)
        self.assertEqual(self.upstream.frames, [raw])
        self.assertEqual(AuditMonitor([self.path]).refresh()[0].audit_status, 'lowered')
        self.assertLess(self.path.stat().st_size, 3000)


class ObserverIdentityTests(unittest.TestCase):
    def test_unknown_response_and_duplicate_terminal_cannot_complete_next_request(self):
        from websocket_capture import ResponsesObserver
        from unittest.mock import Mock
        writer = Mock()
        observer = ResponsesObserver(writer)
        request = dict(type='response.create', model='m', reasoning={'effort':'xhigh'})
        observer.client(request)
        observer.client(request)
        observer.server(dict(type='response.created', response={'id':'first'}))
        observer.server(dict(type='response.completed', response={'id':'unrelated'}))
        observer.server(dict(type='response.completed', response={'id':'first'}))
        observer.server(dict(type='response.completed', response={'id':'first'}))
        observer.close()
        events = [call.args[1] for call in writer.emit.call_args_list]
        self.assertEqual(events, ['request_sent', 'request_sent', 'response_created', 'response_completed', 'response_incomplete'])

    def test_error_after_created_terminates_its_lane_and_missing_effort_is_not_invented(self):
        from websocket_capture import ResponsesObserver
        from unittest.mock import Mock
        writer = Mock()
        observer = ResponsesObserver(writer)
        observer.client(dict(type='response.create', stream_id='main', model='m'))
        observer.server(dict(type='response.created', stream_id='main', response={'id':'resp'}))
        observer.server(dict(type='error', stream_id='main', error={'message':'PRIVATE'}))
        observer.close()
        self.assertEqual([call.args[1] for call in writer.emit.call_args_list],
                         ['request_sent', 'response_created', 'response_failed'])
        self.assertNotIn('PRIVATE', repr(writer.emit.call_args_list))
        self.assertNotIn('reasoning', writer.emit.call_args_list[-1].args[2])


if __name__ == '__main__':
    unittest.main()
