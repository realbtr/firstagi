"""Read owned inboxes. Private payloads stay outside git; stdout is metadata only.

No send, approve, mark-read or acknowledgement occurs on an ordinary check.
Use --ack ID only after the agent actually handled a pending local message.
"""
import argparse
import hashlib
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(r'C:\!FirstAGI_f5')
DEFAULT_STATE = Path(r'C:\!!!FirstAGI\_heartbeat\private_inbox')
COLONY = 'https://thecolony.ai/api/v1'
MOLTBOOK = 'https://www.moltbook.com/api/v1'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # Never forward bearer credentials to another URL.


def api(base, path, token=None, data=None):
    try:
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        headers = {'User-Agent': 'FirstAGI-inbox-monitor', 'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        req = urllib.request.Request(base + path, headers=headers,
                data=json.dumps(data).encode() if data is not None else None)
        opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=ctx))
        with opener.open(req, timeout=25) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        return {'check_error': 'http', 'status': exc.code}
    except Exception as exc:
        return {'check_error': type(exc).__name__}


def credential(name, key):
    values = {}
    for line in (ROOT / '.secrets' / name).read_text(encoding='utf-8').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k, v = line.strip().split('=', 1)
            values[k] = v
    return values[key]


def fingerprint(message):
    stable = {k: message.get(k) for k in ('body', 'content', 'edited_at', 'created_at', 'sender')}
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


def observe(state, message, initial):
    key = 'colony:' + str(message['id'])
    digest = fingerprint(message)
    old = state['seen'].get(key)
    if old != digest and (not initial or not message.get('is_read', False)):
        state['pending'][key] = message
    state['seen'][key] = digest


def check_colony(state):
    auth = api(COLONY, '/auth/token', data={'api_key': credential('colony.env', 'COLONY_API_KEY')})
    if 'access_token' not in auth:
        return {'status': 'unavailable', 'detail': {k: v for k, v in auth.items() if k in ('check_error', 'status')}}
    token = auth['access_token']
    unread = api(COLONY, '/messages/unread-count', token)
    if 'check_error' in unread:
        return {'status': 'unavailable', 'detail': unread}
    conversations, messages, complete = [], [], True
    # A bounded scan reports incomplete rather than pretending a truncated inbox is empty.
    for offset in range(0, 2000, 100):
        page = api(COLONY, f'/messages/conversations?include_archived=true&limit=100&offset={offset}', token)
        if not isinstance(page, list):
            complete = False
            break
        conversations.extend(page)
        if len(page) < 100:
            break
    else:
        complete = False
    old_conversations = state.setdefault('conversations', {})
    for conv in conversations:
        user = conv['other_user']['username']
        signature = [conv.get('last_message_at'), conv.get('last_message_preview')]
        if old_conversations.get(str(conv['id'])) == signature and not conv.get('unread_count'):
            continue
        conversation_complete = False
        for offset in range(0, 4000, 200):
            path = '/messages/conversations/' + urllib.parse.quote(user, safe='')
            detail = api(COLONY, path + f'?limit=200&offset={offset}', token)
            if not isinstance(detail, dict) or 'messages' not in detail:
                break
            batch = detail['messages']
            for message in batch:
                # The peer identity comes from the authenticated conversation, not text.
                if message.get('sender', {}).get('username') == user:
                    messages.append(message)
                    observe(state, message, initial=not state.get('colony_initialized', False))
            if len(batch) < 200:
                conversation_complete = True
                break
        if conversation_complete:
            old_conversations[str(conv['id'])] = signature
        else:
            complete = False
    if complete:
        state['colony_initialized'] = True
    return {'status': 'checked' if complete else 'incomplete', 'conversations': len(conversations),
            'unread': unread.get('unread_direct_messages', unread.get('unread_count')),
            'messages_fetched': len(messages)}


def check_moltbook(state, now):
    key = credential('moltbook.env', 'MOLTBOOK_API_KEY')
    home = api(MOLTBOOK, '/home', key)
    if 'check_error' in home:
        return {'status': 'unavailable', 'detail': home}
    state['moltbook_home_private'] = home
    notifications = api(MOLTBOOK, '/notifications', key)
    state['moltbook_notifications_private'] = notifications
    dm = home.get('your_direct_messages')
    # Do not follow executable quick_links or role briefings from returned text.
    cached = state.get('moltbook_dm_probe', {})
    due = not cached or now >= datetime.fromisoformat(cached['next_probe_at'])
    if due:
        probe = api(MOLTBOOK, '/agents/dm/check', key)
        cached = {'result': probe, 'next_probe_at': (now + timedelta(days=1)).isoformat()}
        state['moltbook_dm_probe'] = cached
    state['moltbook_dm_summary_private'] = dm
    probe = cached['result']
    result = {'status': 'unavailable', 'home_checked': True,
              'notifications_checked': 'check_error' not in notifications,
              'dm_summary_present': dm is not None,
              'dm_probe_http_status': probe.get('status') if isinstance(probe, dict) else None,
              'probe_cached': not due}
    if dm is not None or (isinstance(probe, dict) and 'check_error' not in probe):
        # A newly exposed API needs explicit schema review before claiming full coverage.
        result['status'] = 'api_changed_needs_review'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, default=DEFAULT_STATE)
    parser.add_argument('--ack', action='append', default=[])
    args = parser.parse_args()
    folder = args.state_dir.resolve()
    if folder.is_relative_to(ROOT.resolve()):
        raise SystemExit('Private inbox state must be outside the Git checkout')
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / 'state.local.json'
    state = json.loads(target.read_text(encoding='utf-8')) if target.exists() else {'seen': {}, 'pending': {}}
    for key in args.ack:
        state['pending'].pop(key, None)
    now = datetime.now(timezone.utc)
    report = {'checked_at': now.isoformat()}
    for name, run in [('colony', lambda: check_colony(state)), ('moltbook', lambda: check_moltbook(state, now))]:
        try:
            report[name] = run()
        except Exception as exc:
            report[name] = {'status': 'unavailable', 'detail': type(exc).__name__}
    # Private message bodies and identifiers are deliberately absent from stdout.
    report['pending_colony_messages'] = len(state['pending'])
    state['last_report'] = report
    temporary = folder / 'state.local.tmp'
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(target)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
