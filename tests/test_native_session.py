import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import os
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from requests.cookies import create_cookie, RequestsCookieJar

import playlocal_server as server


class CookieStore:
    def __init__(self, cookies):
        self.jar = RequestsCookieJar()
        for cookie in cookies:
            self.jar.set_cookie(cookie)

    def get_dict(self):
        return {cookie.name: cookie.value for cookie in self.jar}


class NativeSessionTests(unittest.TestCase):
    """Exercise real signing, login parsing and capability redemption offline."""

    def setUp(self):
        self.env = patch.dict(os.environ, {
            'COURTFLOW_BROWSER_SECRET': 'offline-native-session-test-secret',
            'PLAYLOCAL_ACCOUNT_1_USERNAME': 'one@example.invalid',
            'PLAYLOCAL_ACCOUNT_1_PASSWORD': 'test-only-password-one',
            'PLAYLOCAL_ACCOUNT_1_NAME': 'First account',
            'PLAYLOCAL_ACCOUNT_2_USERNAME': 'two@example.invalid',
            'PLAYLOCAL_ACCOUNT_2_PASSWORD': 'test-only-password-two',
            'PLAYLOCAL_ACCOUNT_2_NAME': 'Second account',
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.clock = patch.object(server.time, 'time', return_value=1000.25)
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)
        self.previous_sessions = dict(server.SESSIONS)
        self.previous_bridges = dict(server.BROWSER_BRIDGES)
        server.SESSIONS.clear()
        server.BROWSER_BRIDGES.clear()
        self.addCleanup(self.restore_registries)

        self.slot = {
            'slotId': '42:54:2026-10-09:480',
            'facilityId': '42', 'facilityName': 'West Roxbury High School',
            'courtId': '54', 'courtName': 'Court 2', 'date': '2026-10-09',
            'start': 480, 'end': 540, 'priceCents': 0,
            'searchLocation': 'West Roxbury',
            'untrustedExtra': 'must not be transferred',
        }
        self.url = server.BASE + '/facilities/west-roxbury/reservations/new?date=2026-10-09'
        form = server.soup('''<form action="/reservations" method="post">
            <select name="reservation[reservable_id]">
              <option value="53">Court 1</option>
              <option value="54">Court 2</option>
            </select><input name="reservation[date]" type="text">
            </form>''').form
        self.page = SimpleNamespace(url=self.url, text=str(form))
        self.prepare = patch.object(server, '_reservation_page_for_query',
            return_value=(self.page, server.soup(str(form)), form, '', '', '', self.url))
        self.prepare_mock = self.prepare.start()
        self.addCleanup(self.prepare.stop)
        self.account_one, self.session_one = self.login_account('server-1', 'one')
        self.account_two, self.session_two = self.login_account('server-2', 'two')

    def restore_registries(self):
        server.SESSIONS.clear()
        server.SESSIONS.update(self.previous_sessions)
        server.BROWSER_BRIDGES.clear()
        server.BROWSER_BRIDGES.update(self.previous_bridges)

    def login_account(self, account_id, marker):
        session = SimpleNamespace(cookies=CookieStore([
            create_cookie('_playlocal_session', 'session-' + marker,
                          domain='.playlocal.com', secure=True, rest={'HttpOnly': None}),
        ]))
        login_page = SimpleNamespace(url=server.BASE + '/sign_in',
            text='''<form action="/sign_in" method="post">
            <input name="user[email]" type="email">
            <input name="user[password]" type="password"></form>''',
            raise_for_status=lambda: None)
        home = SimpleNamespace(url=server.BASE + '/', text='Signed in',
                               raise_for_status=lambda: None)
        with patch.object(server, 'browser_session', return_value=session), \
             patch.object(server, 'browser_get', side_effect=[home, login_page]) as get, \
             patch.object(server, 'submit', return_value=home) as submit:
            result = server.login_server_account(account_id)
            self.assertEqual(get.call_count, 2)
            submitted = submit.call_args.args[3]
            configured = server.configured_server_accounts()[account_id]
            self.assertEqual(submitted, {'user[email]': configured['username'],
                                         'user[password]': configured['password']})
        return result, session

    def issue(self, account_id='server-1', session=None, native=True, slot=None):
        account = session or (self.account_one if account_id == 'server-1' else self.account_two)
        return server.issue_browser_ticket({
            'accountId': account_id, 'sessionToken': account['sessionToken'],
            'slot': self.slot if slot is None else slot,
        }, native=native)

    def payload(self, ticket):
        body = ticket.split('.')[0]
        return json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))

    def signed(self, payload):
        body = server._b64url(json.dumps(payload, sort_keys=True,
                                        separators=(',', ':')).encode())
        sig = server._b64url(hmac.new(os.environ['COURTFLOW_BROWSER_SECRET'].encode(),
                                     body.encode(), hashlib.sha256).digest())
        return body + '.' + sig

    def assert_api_error(self, code, operation):
        with self.assertRaises(server.ApiError) as raised:
            operation()
        self.assertEqual(raised.exception.code, code)
        return raised.exception

    def test_issued_ticket_redeems_authenticated_session_without_credentials(self):
        issued = self.issue()
        payload = self.payload(issued['ticket'])
        self.assertEqual(issued['expiresInSeconds'], 120)
        self.assertEqual(payload['aud'], 'native')
        self.assertEqual(payload['exp'], 1120)
        self.assertEqual(payload['accountId'], 'server-1')
        result = server.native_session_material(issued['ticket'])
        self.assertEqual(result['accountName'], 'First account')
        self.assertEqual(result['reservationUrl'], self.url)
        self.assertEqual(result['cookies'][0]['value'], 'session-one')
        self.assertEqual(set(result), {'cookies', 'slot', 'reservationUrl', 'accountName'})
        combined = json.dumps({'issued': payload, 'result': result})
        for private in ('test-only-password-one', 'one@example.invalid', server.UA,
                        self.account_one['sessionToken'], 'untrustedExtra'):
            self.assertNotIn(private, combined)
        self.assertNotIn(payload['bridgeId'], server.BROWSER_BRIDGES)

    def test_issuance_prepares_requested_account_and_exact_court(self):
        self.issue()
        session, query, facility = self.prepare_mock.call_args.args
        self.assertIs(session, self.session_one)
        self.assertEqual(query, {'date': '2026-10-09', 'location': 'West Roxbury',
            'sport': 'tennis', 'start': 480, 'end': 540, 'facilityId': '42'})
        self.assertEqual(facility, '42')
        bad_slot = {**self.slot, 'courtId': '999', 'courtName': 'Court 99'}
        before = set(server.BROWSER_BRIDGES)
        self.assert_api_error('COURT_UNAVAILABLE', lambda: self.issue(slot=bad_slot))
        self.assertEqual(set(server.BROWSER_BRIDGES), before)

    def test_replay_fails_after_one_redemption(self):
        ticket = self.issue()['ticket']
        server.native_session_material(ticket)
        self.assert_api_error('BROWSER_SESSION', lambda: server.native_session_material(ticket))

    def test_expired_ticket_fails_at_expiry_boundary(self):
        ticket = self.issue()['ticket']
        self.now.return_value = self.payload(ticket)['exp']
        self.assert_api_error('NATIVE_SESSION', lambda: server.native_session_material(ticket))

    def test_expired_bridge_fails_even_with_unexpired_signature(self):
        ticket = self.issue()['ticket']
        server.BROWSER_BRIDGES[self.payload(ticket)['bridgeId']]['exp'] = 999
        self.assert_api_error('BROWSER_SESSION', lambda: server.native_session_material(ticket))

    def test_tampered_body_or_signature_cannot_consume_valid_bridge(self):
        ticket = self.issue()['ticket']
        body, sig = ticket.split('.')
        altered = dict(self.payload(ticket), accountId='server-2')
        forged_body = server._b64url(json.dumps(altered).encode())
        for malformed in (forged_body + '.' + sig, body + '.invalid', '', None,
                          'invalid', 'a.b.c', 'x' * 12001):
            with self.subTest(ticket=repr(malformed)[:80]):
                self.assert_api_error('NATIVE_SESSION',
                    lambda: server.native_session_material(malformed))
        self.assertEqual(server.native_session_material(ticket)['accountName'], 'First account')

    def test_remote_audience_ticket_cannot_be_redeemed_as_native(self):
        ticket = self.issue(native=False)['ticket']
        self.assert_api_error('NATIVE_SESSION', lambda: server.native_session_material(ticket))

    def test_native_ticket_cannot_consume_remote_bridge_or_remote_endpoint(self):
        remote = self.payload(self.issue(native=False)['ticket'])
        self.assert_api_error('BROWSER_SESSION', lambda:
            server.native_session_material(self.signed({**remote, 'aud': 'native'})))
        native = self.payload(self.issue()['ticket'])
        self.assert_api_error('BROWSER_SESSION', lambda:
            server.browser_session_material(native['bridgeId'], 'server-1'))
        self.assertEqual(server.native_session_material(self.signed(native))['accountName'],
                         'First account')

    def test_redemption_uses_stored_canonical_slot_and_url(self):
        ticket = self.issue()['ticket']
        payload = self.payload(ticket)
        altered = {**payload, 'slot': {**payload['slot'], 'courtId': '53', 'start': 900},
                   'reservationUrl': 'https://other.example.invalid/', 'accountName': 'Injected'}
        self.slot['courtId'] = '278'
        self.slot['start'] = 960
        result = server.native_session_material(self.signed(altered))
        self.assertEqual(result['slot']['courtId'], '54')
        self.assertEqual(result['slot']['start'], 480)
        self.assertEqual(result['reservationUrl'], self.url)
        self.assertEqual(result['accountName'], 'First account')

    def test_cookie_domains_cloudflare_names_and_httponly_are_preserved_correctly(self):
        self.session_one.cookies = CookieStore([
            create_cookie('_playlocal_session', 'auth', domain='.playlocal.com',
                          path='/user', secure=False, rest={'HttpOnly': None}),
            create_cookie('preferences', 'prefs', domain='www.playlocal.com', rest={}),
            create_cookie('host_session', 'host', domain='playlocal.com',
                          rest={'httponly': True}),
            create_cookie('cf_clearance', 'forbidden', domain='.playlocal.com'),
            create_cookie('__cf_bm', 'forbidden', domain='.playlocal.com'),
            create_cookie('_cf_chl', 'forbidden', domain='.playlocal.com'),
            create_cookie('CF_CASE', 'forbidden', domain='.playlocal.com'),
            create_cookie('foreign_session', 'foreign', domain='.example.invalid'),
            create_cookie('lookalike', 'foreign', domain='www.playlocal.com.example.invalid'),
        ])
        cookies = server.native_session_material(self.issue()['ticket'])['cookies']
        self.assertEqual({c['name'] for c in cookies},
                         {'_playlocal_session', 'preferences', 'host_session'})
        indexed = {c['name']: c for c in cookies}
        self.assertTrue(indexed['_playlocal_session']['httpOnly'])
        self.assertTrue(indexed['host_session']['httpOnly'])
        self.assertFalse(indexed['preferences']['httpOnly'])
        self.assertEqual(indexed['_playlocal_session']['path'], '/user')
        self.assertEqual(indexed['_playlocal_session']['domain'], '.playlocal.com')
        self.assertTrue(all(c['secure'] for c in cookies))

    def test_filtered_jar_cannot_fall_back_and_relabel_foreign_cookies(self):
        self.session_one.cookies = CookieStore([
            create_cookie('foreign_session', 'foreign', domain='.example.invalid'),
            create_cookie('cf_clearance', 'forbidden', domain='.playlocal.com'),
        ])
        self.assert_api_error('BROWSER_SESSION', lambda:
            server.native_session_material(self.issue()['ticket']))

    def test_account_sessions_and_bridge_ownership_are_isolated(self):
        one, two = self.issue()['ticket'], self.issue(account_id='server-2')['ticket']
        altered = {**self.payload(one), 'accountId': 'server-2'}
        self.assert_api_error('BROWSER_SESSION', lambda:
            server.native_session_material(self.signed(altered)))
        second = server.native_session_material(two)
        first = server.native_session_material(one)
        self.assertEqual(second['accountName'], 'Second account')
        self.assertEqual(second['cookies'][0]['value'], 'session-two')
        self.assertEqual(first['cookies'][0]['value'], 'session-one')
        self.assert_api_error('AUTH_REJECTED', lambda:
            self.issue(account_id='server-2', session=self.account_one))

    def test_concurrent_redemptions_allow_exactly_one_success(self):
        ticket = self.issue()['ticket']
        barrier = threading.Barrier(6)

        def redeem():
            barrier.wait(timeout=5)
            try:
                return ('ok', server.native_session_material(ticket))
            except server.ApiError as error:
                return ('error', error.code)

        with ThreadPoolExecutor(max_workers=6) as pool:
            outcomes = list(pool.map(lambda _: redeem(), range(6)))
        self.assertEqual(sum(kind == 'ok' for kind, _ in outcomes), 1)
        self.assertEqual([value for kind, value in outcomes if kind == 'error'],
                         ['BROWSER_SESSION'] * 5)


if __name__ == '__main__':
    unittest.main()
