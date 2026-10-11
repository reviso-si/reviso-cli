"""OAuth uses real HTTP exchange and a loopback callback; only browser launch is replaced."""
import base64
import hashlib
import json
import socket
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from reviso_cli import cli
from reviso_cli.cli import oauth_login
from reviso_cli.cli.credential_file import read_credentials


class OAuthHandler(BaseHTTPRequestHandler):
    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        origin = self.server.origin
        if self.path == '/.well-known/oauth-authorization-server':
            self.send_json({'issuer': origin, 'code_challenge_methods_supported': ['S256'],
                            'grant_types_supported': ['authorization_code', 'refresh_token'],
                            **{key + '_endpoint': origin + '/oauth/' + path for key, path in
                               [('authorization', 'authorize'), ('registration', 'register'), ('token', 'token')]}})
        else:
            self.send_json({'authorization': self.headers.get('Authorization')})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        if self.path == '/oauth/register':
            data = json.loads(body)
            self.server.redirect = data['redirect_uris'][0]
            self.send_json({'client_id': 'test-client'})
            return
        data = {key: value[0] for key, value in parse_qs(body.decode()).items()}
        self.server.exchanges.append(data)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(data['code_verifier'].encode()).digest()).decode().rstrip('=')
        if data['code'] != 'test-code' or challenge != self.server.challenge:
            self.send_json({'error': 'invalid_grant'}, 400)
            return
        self.send_json({'access_token': 'test-access', 'refresh_token': 'test-refresh',
                        'token_type': 'Bearer', 'expires_in': 3600})

    def log_message(self, *_):
        pass


@pytest.fixture
def oauth_server(monkeypatch, tmp_path):
    lookup = socket.getaddrinfo
    def loopback_only(host, *args, **kwargs):
        assert host in {'127.0.0.1', 'localhost', '::1'}, 'test attempted a non-loopback request'
        return lookup(host, *args, **kwargs)
    monkeypatch.setattr(socket, 'getaddrinfo', loopback_only)
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    monkeypatch.setenv('REVISO_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.delenv('REVISO_SERVER', raising=False)
    monkeypatch.delenv('REVISO_AUTOMATION_KEY', raising=False)
    with ThreadingHTTPServer(('127.0.0.1', 0), OAuthHandler) as server:
        server.origin = f'http://127.0.0.1:{server.server_port}'
        server.exchanges = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield server
        server.shutdown()
        thread.join()


def test_browser_login_exchanges_pkce_then_authenticates_commands(oauth_server, monkeypatch, capsys):
    server = oauth_server
    futures = []
    with ThreadPoolExecutor(max_workers=1) as pool:
        def browser(url):
            params = {key: value[0] for key, value in parse_qs(urlsplit(url).query).items()}
            assert params['resource'] == server.origin + '/mcp'
            assert params['code_challenge_method'] == 'S256'
            server.challenge = params['code_challenge']
            futures.append(pool.submit(callbacks, params))
            return True
        monkeypatch.setattr(oauth_login.webbrowser, 'open', browser)
        cli.main(['auth', 'login', '--server', server.origin])
        for future in futures:
            future.result(timeout=3)
    assert len(server.exchanges) == 1
    assert server.exchanges[0]['redirect_uri'] == server.redirect
    assert read_credentials()['server'] == server.origin
    assert cli._client().workspaces()['authorization'] == 'Bearer test-access'
    output = capsys.readouterr().out
    assert 'Logged in' in output
    assert 'test-access' not in output and 'test-refresh' not in output
    cli.main(['auth', 'logout'])
    monkeypatch.setenv('REVISO_SERVER', server.origin)
    assert cli._client().workspaces()['authorization'] is None


def callbacks(params):
    target = params['redirect_uri']
    for query in ['code=test-code&state=wrong', f"code=a&code=b&state={params['state']}"]:
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(target + '?' + query, timeout=2)
        assert error.value.code == 400
    with urllib.request.urlopen(target + '?' + urlencode({'code': 'test-code', 'state': params['state']}), timeout=2) as response:
        assert response.status == 200
