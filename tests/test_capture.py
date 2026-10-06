import http.client
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

import audit_capture
from audit_capture import create_capture_server
from reasoning_audit import AuditMonitor


class Upstream(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        self.server.seen.append((self.path, body, self.headers.get('Authorization')))
        request = json.loads(gzip.decompress(body) if self.headers.get('Content-Encoding') == 'gzip' else body)
        value = {'id':'resp-capture', 'model':'test-model', 'reasoning':{'effort':'low'},
                 'usage':{'output_tokens':100,'output_tokens_details':{'reasoning_tokens':40}},
                 'output':[{'text':'PRIVATE OUTPUT'}]}
        if request.get('invalid_json'):
            result = b'not a response JSON'
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(result)))
            self.end_headers()
            self.wfile.write(result)
        elif request.get('fail'):
            result = b'{"error":"PRIVATE ERROR"}'
            self.send_response(503)
            self.send_header('Content-Length', str(len(result)))
            self.end_headers()
            self.wfile.write(result)
        elif not request.get('stream'):
            result = json.dumps(value).encode()
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(result)))
            self.end_headers()
            self.wfile.write(result)
        else:
            self.send_response(200)
            if not request.get('omit_content_type'):
                self.send_header('Content-Type','application/json' if request.get('wrong_content_type') else 'text/event-stream')
            self.send_header('Connection','close')
            self.end_headers()
            created = dict(value, reasoning={'effort':'high'}, usage=None, output=[])
            first = ('data: '+json.dumps({'type':'response.created','response':created})+'\r\n\r\n').encode()
            for i in range(0,len(first),7):
                self.wfile.write(first[i:i+7])
                self.wfile.flush()
            self.server.gate.wait(3)
            if not request.get('incomplete'):
                self.wfile.write(('data: '+json.dumps({'type':'response.completed','response':value})+'\n\n').encode())
                self.wfile.flush()
            self.close_connection = True


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'audit.jsonl'
        self.upstream = ThreadingHTTPServer(('127.0.0.1',0),Upstream)
        self.upstream.seen, self.upstream.gate = [], threading.Event()
        self.proxy = create_capture_server(f'http://127.0.0.1:{self.upstream.server_port}/v1',self.path,port=0)
        for server in (self.upstream,self.proxy):
            threading.Thread(target=server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.upstream.gate.set()
        for server in (self.proxy,self.upstream):
            server.shutdown()
            server.server_close()
        self.temp.cleanup()

    def connect(self, **extra):
        request = dict(model='test-model',reasoning={'effort':'xhigh'},input='PRIVATE INPUT',stream=True,**extra)
        body = json.dumps(request).encode()
        conn = http.client.HTTPConnection('127.0.0.1',self.proxy.server_port,timeout=5)
        conn.request('POST','/v1/responses',body,{'Content-Type':'application/json',
                     'Authorization':'Bearer PRIVATE KEY'})
        return conn, conn.getresponse(), body

    def test_sse_streams_before_completion_preserves_body_and_redacts(self):
        conn, response, body = self.connect()
        first = response.read1(4096)
        self.assertIn(b'data:',first)
        self.assertFalse(self.upstream.gate.is_set())
        self.upstream.gate.set()
        output = first + response.read()
        conn.close()
        self.assertIn(b'PRIVATE OUTPUT',output)
        self.assertEqual(self.upstream.seen[0],('/v1/responses',body,'Bearer PRIVATE KEY'))
        row = AuditMonitor([self.path]).refresh()[0]
        self.assertEqual(row.audit_status,'lowered')
        self.assertEqual((row.first_effort,row.final_effort),('high','low'))
        saved = self.path.read_text(encoding='utf-8')
        self.assertNotIn('PRIVATE',saved)
        self.assertNotIn('Authorization',saved)

    def test_nonstream_failure_and_missing_terminal(self):
        for extra, expected in [({'stream':False},'lowered'),({'fail':True},'failed'),({'incomplete':True},'incomplete')]:
            self.upstream.gate.set()
            # Explicit dict update keeps the helper's defaults overridable.
            conn = http.client.HTTPConnection('127.0.0.1',self.proxy.server_port,timeout=5)
            body = json.dumps(dict(model='test-model',reasoning={'effort':'xhigh'},stream=extra.get('stream',True),
                                   **{k:v for k,v in extra.items() if k != 'stream'})).encode()
            conn.request('POST','/v1/responses',body,{'Content-Type':'application/json'})
            result = conn.getresponse()
            result.read()
            conn.close()
            rows = AuditMonitor([self.path]).refresh()
            self.assertEqual(rows[0].audit_status,expected)
            if extra.get('stream') is False:
                self.assertEqual(rows[0].first_display,'不适用')

    def test_invalid_websocket_handshake_and_upstream_url_validated(self):
        conn = http.client.HTTPConnection('127.0.0.1',self.proxy.server_port,timeout=5)
        conn.request('GET','/v1/responses',headers={'Upgrade':'websocket','Connection':'Upgrade'})
        response = conn.getresponse()
        self.assertEqual(response.status,400)
        self.assertIn(b'WebSocket',response.read())
        conn.close()
        self.assertEqual(self.upstream.seen,[])
        for url in ('ftp://example.com','https://key:secret@example.com/v1','https://example.com/v1?key=secret'):
            with self.assertRaises(ValueError):
                create_capture_server(url,self.path,port=0)

    def test_concurrent_requests_have_separate_identity_and_complete_lines(self):
        self.upstream.gate.set()
        results, failures = [], []
        def consume():
            try:
                conn,response,_ = self.connect()
                results.append(response.read())
                conn.close()
            except Exception as exc:
                failures.append(exc)
        threads = [threading.Thread(target=consume) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(failures,[])
        self.assertEqual(len(results),2)
        monitor = AuditMonitor([self.path])
        rows = monitor.refresh()
        self.assertEqual(len(rows),2)
        self.assertEqual(len({r.request_id for r in rows}),2)
        self.assertEqual(monitor.bad_lines,0)
        self.assertTrue(all(r.audit_status == 'lowered' for r in rows))

    def test_sse_without_correct_content_type_still_captures_real_event_fields(self):
        self.upstream.gate.set()
        for flags in ({'omit_content_type':True}, {'wrong_content_type':True}):
            conn,response,_ = self.connect(**flags)
            response.read();conn.close()
            row = AuditMonitor([self.path]).refresh()[0]
            self.assertEqual((row.outbound_effort,row.first_effort,row.final_effort,row.reasoning_tokens),
                             ('xhigh','high','low',40))
            self.assertEqual(row.audit_status,'lowered')

    def test_invalid_nonstream_body_is_incomplete_not_completed(self):
        self.upstream.gate.set()
        conn,response,_ = self.connect(invalid_json=True)
        response.read();conn.close()
        row = AuditMonitor([self.path]).refresh()[0]
        self.assertEqual(row.request_state,'incomplete')

    def test_compressed_request_fallback_preserves_bytes_and_does_not_guess_outbound_effort(self):
        self.upstream.gate.set()
        body = gzip.compress(json.dumps(dict(model='test-model', reasoning={'effort':'xhigh'}, stream=True)).encode())
        conn = http.client.HTTPConnection('127.0.0.1', self.proxy.server_port, timeout=5)
        conn.request('POST', '/v1/responses', body, {'Content-Encoding':'gzip'})
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        response.read()
        conn.close()
        self.assertEqual(self.upstream.seen[0][1], body)
        row = AuditMonitor([self.path]).refresh()[0]
        self.assertIsNone(row.outbound_effort)
        self.assertEqual(row.audit_status, 'unknown')
        self.assertEqual(row.request_state, 'completed')


class ProxyRoutingTests(unittest.TestCase):
    def test_https_uses_system_proxy_connect_with_origin_tls(self):
        with patch('audit_capture.getproxies', return_value={'https':'http://127.0.0.1:7897'}), \
                patch('audit_capture.proxy_bypass', return_value=False):
            conn, absolute = audit_capture.upstream_connection(urlsplit('https://chatgpt.com/backend-api/codex'), 10)
        self.assertIsInstance(conn, http.client.HTTPSConnection)
        self.assertEqual((conn.host, conn.port), ('127.0.0.1',7897))
        self.assertEqual((conn._tunnel_host, conn._tunnel_port), ('chatgpt.com',443))
        self.assertFalse(absolute)
        conn.close()

    def test_loopback_stays_direct_and_http_proxy_uses_absolute_target(self):
        with patch('audit_capture.getproxies', return_value={'http':'http://proxy.example:8080'}), \
                patch('audit_capture.proxy_bypass', return_value=False):
            local, absolute = audit_capture.upstream_connection(urlsplit('http://127.0.0.1:8765/v1'), 10)
            self.assertEqual((local.host, local.port, absolute), ('127.0.0.1',8765,False))
            local.close()
            remote, absolute = audit_capture.upstream_connection(urlsplit('http://provider.example/v1'), 10)
            self.assertEqual((remote.host, remote.port, absolute), ('proxy.example',8080,True))
            remote.close()

    def test_unsupported_proxy_rejected_without_exposing_credentials(self):
        for value in ('socks5://127.0.0.1:1080', 'http://PRIVATE:SECRET@proxy.example:8080'):
            with patch('audit_capture.getproxies', return_value={'https':value}), \
                    patch('audit_capture.proxy_bypass', return_value=False):
                with self.assertRaises(ValueError) as caught:
                    audit_capture.upstream_connection(urlsplit('https://chatgpt.com'), 10)
                self.assertNotIn('PRIVATE',str(caught.exception))
                self.assertNotIn('SECRET',str(caught.exception))


if __name__ == '__main__':
    unittest.main()
