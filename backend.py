"""
Backend Flask - API REST pour le panel web Tinder Bot
Proxy par compte : chaque compte peut avoir son propre proxy
"""

from flask import Flask, request, jsonify, session
from flask_cors import CORS
import json
import time
import random
import threading
import uuid
import os
import hashlib
import secrets

try:
    from curl_cffi import requests as curl_requests
    CURL_CFFI_AVAILABLE = True
except ImportError:
    import requests as curl_requests
    CURL_CFFI_AVAILABLE = False

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

GROQ_API_KEY = "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"
GROQ_MODEL = "llama-3.3-70b-versatile"

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'tinderbot-secret-key-change-me-in-prod')
CORS(app, supports_credentials=True, origins=['*'])

import threading as _threading
_tokens_lock = _threading.Lock()
TOKENS_FILE = "active_tokens.json"

def _load_tokens():
    try:
        with open(TOKENS_FILE, 'r') as f:
            data = json.load(f)
        now = time.time()
        return {k: v for k, v in data.items() if now - v.get('_created', now) < 86400}
    except:
        return {}

def _save_tokens(tokens):
    with open(TOKENS_FILE, 'w') as f:
        json.dump(tokens, f, indent=2)

active_tokens = _load_tokens()  # Chargé au démarrage

def generate_token():
    return secrets.token_hex(32)

def get_token_from_request():
    token = request.headers.get('X-Auth-Token', '') or ''
    if token and token not in active_tokens:
        # Recharge depuis disque (redémarrage potentiel)
        fresh = _load_tokens()
        active_tokens.update(fresh)
    return token

def require_auth(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        token = get_token_from_request()
        if not token or token not in active_tokens:
            return jsonify({'success': False, 'error': 'Non authentifié'}), 401
        return f(*args, **kwargs)
    return decorated

def require_admin(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        token = get_token_from_request()
        if not token or token not in active_tokens:
            return jsonify({'success': False, 'error': 'Non authentifié'}), 401
        if active_tokens[token].get('role') != 'admin':
            return jsonify({'success': False, 'error': 'Accès refusé — admin requis'}), 403
        return f(*args, **kwargs)
    return decorated

def current_user_data():
    token = get_token_from_request()
    return active_tokens.get(token, {})

def current_user_id():
    return current_user_data().get('user_id', 'default')

# ============================================================
# HELPERS
# ============================================================

def generate_session_id():
    return str(uuid.uuid4())

def generate_request_id():
    return str(uuid.uuid4())

def get_current_ip(proxies=None):
    try:
        resp = requests.get('https://api.ipify.org?format=json', proxies=proxies, timeout=10, verify=False)
        return resp.json()['ip']
    except:
        return None

def get_proxies_for_account(account, user_id="default"):
    """
    Retourne le proxy à utiliser pour ce compte.
    Priorité : proxy du compte > proxy global de l'utilisateur
    """
    # Proxy spécifique au compte
    account_proxy = account.get('proxy_url', '').strip() if account.get('proxy_enabled') else ''
    if account_proxy:
        return {'http': account_proxy, 'https': account_proxy}
    # Fallback : proxy global de l'utilisateur
    return get_proxies(user_id)

# ============================================================
# FICHIERS DE DONNÉES
# ============================================================

DATA_DIR = '/data'
os.makedirs(DATA_DIR, exist_ok=True)

TOKENS_FILE        = f"{DATA_DIR}/active_tokens.json"
ACCOUNTS_FILE      = f"{DATA_DIR}/tinder_accounts.json"
PROXIES_FILE       = f"{DATA_DIR}/user_proxies.json"
HISTORY_FILE       = f"{DATA_DIR}/message_history.json"
STATS_FILE         = f"{DATA_DIR}/tinder_stats.json"
STATS_HISTORY_FILE = f"{DATA_DIR}/tinder_stats_history.json"
USERS_FILE         = f"{DATA_DIR}/panel_users.json"
TAGS_FILE          = f"{DATA_DIR}/panel_tags.json"
AUTOMATION_FILE    = f"{DATA_DIR}/automation_config.json"
SETTINGS_FILE      = f"{DATA_DIR}/panel_settings.json"
PROXY_POOL_FILE    = f"{DATA_DIR}/proxy_pool.json"

# --- SETTINGS ---

def load_settings(user_id="default"):
    try:
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f).get(str(user_id), {})
    except:
        return {}

def save_settings(settings, user_id="default"):
    try:
        with open(SETTINGS_FILE, 'r') as f:
            all_data = json.load(f)
    except:
        all_data = {}
    all_data[str(user_id)] = settings
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(all_data, f, indent=2)

# --- TAGS ---

def load_tags(user_id="default"):
    try:
        with open(TAGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f).get(str(user_id), [])
    except:
        return []

def save_tags(tags, user_id="default"):
    try:
        with open(TAGS_FILE, 'r', encoding='utf-8') as f:
            all_data = json.load(f)
    except:
        all_data = {}
    all_data[str(user_id)] = tags
    with open(TAGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)

# --- STATS HISTORY ---

def load_stats_history(user_id="default"):
    try:
        with open(STATS_HISTORY_FILE, 'r') as f:
            return json.load(f).get(str(user_id), [])
    except:
        return []

def save_stats_history(history, user_id="default"):
    try:
        with open(STATS_HISTORY_FILE, 'r') as f:
            all_data = json.load(f)
    except:
        all_data = {}
    all_data[str(user_id)] = history
    with open(STATS_HISTORY_FILE, 'w') as f:
        json.dump(all_data, f, indent=2)

def record_daily_stats(user_id="default"):
    import datetime
    today = datetime.date.today().isoformat()
    stats = load_stats(user_id)
    history = load_stats_history(user_id)
    existing = next((e for e in history if e['date'] == today), None)
    if existing:
        existing['swipes']   = stats.get('swipes', 0)
        existing['messages'] = stats.get('messages', 0)
        existing['matches']  = stats.get('matches', 0)
        existing['replies']  = stats.get('replies', 0)
        existing['cta_sent'] = stats.get('cta_sent', 0)
    else:
        history.append({
            'date': today,
            'swipes':   stats.get('swipes', 0),
            'messages': stats.get('messages', 0),
            'matches':  stats.get('matches', 0),
            'replies':  stats.get('replies', 0),
            'cta_sent': stats.get('cta_sent', 0),
        })
    save_stats_history(history, user_id)

# --- AUTOMATION ---

def load_automation(user_id="default"):
    try:
        with open(AUTOMATION_FILE, 'r') as f:
            return json.load(f).get(str(user_id), [])
    except:
        return []

def save_automation(tasks, user_id="default"):
    try:
        with open(AUTOMATION_FILE, 'r') as f:
            all_data = json.load(f)
    except:
        all_data = {}
    all_data[str(user_id)] = tasks
    with open(AUTOMATION_FILE, 'w') as f:
        json.dump(all_data, f, indent=2)

# --- AUTH HELPERS ---

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def load_users():
    try:
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

def ensure_admin_exists():
    users = load_users()
    if not users:
        admin_id = str(uuid.uuid4())
        users[admin_id] = {
            'id': admin_id,
            'username': 'admin',
            'password': hash_password('admin123'),
            'role': 'admin',
            'created_at': time.time(),
        }
        save_users(users)
        print("👤 Admin créé — username: admin / password: admin123")

def load_stats(user_id="default"):
    try:
        with open(STATS_FILE, 'r') as f:
            d = json.load(f).get(str(user_id), {})
            return {
                'swipes':   d.get('swipes', 0),
                'messages': d.get('messages', 0),
                'matches':  d.get('matches', 0),
                'replies':  d.get('replies', 0),
                'cta_sent': d.get('cta_sent', 0),
            }
    except:
        return {'swipes': 0, 'messages': 0, 'matches': 0, 'replies': 0, 'cta_sent': 0}

def save_stats(stats, user_id="default"):
    import datetime
    try:
        with open(STATS_FILE, 'r') as f:
            all_data = json.load(f)
    except:
        all_data = {}
    existing = all_data.get(str(user_id), {})
    all_data[str(user_id)] = {
        **stats,
        'last_reset': existing.get('last_reset', datetime.date.today().isoformat())
    }
    with open(STATS_FILE, 'w') as f:
        json.dump(all_data, f, indent=2)

def load_accounts(user_id="default"):
    try:
        with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get(str(user_id), [])
    except:
        return []

def save_accounts(accounts, user_id="default"):
    try:
        with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
            all_data = json.load(f)
    except:
        all_data = {}
    all_data[str(user_id)] = accounts
    with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)

def load_proxy(user_id="default"):
    try:
        with open(PROXIES_FILE, 'r') as f:
            return json.load(f).get(str(user_id), {'enabled': False, 'proxy_url': None, 'rotation_link': None})
    except:
        return {'enabled': False, 'proxy_url': None, 'rotation_link': None}

def save_proxy(config, user_id="default"):
    try:
        with open(PROXIES_FILE, 'r') as f:
            all_data = json.load(f)
    except:
        all_data = {}
    all_data[str(user_id)] = config
    with open(PROXIES_FILE, 'w') as f:
        json.dump(all_data, f, indent=2)

def get_proxies(user_id="default"):
    cfg = load_proxy(user_id)
    if cfg['enabled'] and cfg['proxy_url']:
        return {'http': cfg['proxy_url'], 'https': cfg['proxy_url']}
    return None

def load_history(user_id="default"):
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f).get(str(user_id), {})
    except:
        return {}

def save_history(history, user_id="default"):
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            all_data = json.load(f)
    except:
        all_data = {}
    all_data[str(user_id)] = history
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, indent=2, ensure_ascii=False)

def mark_message_sent(user_id, account_user_id, match_id):
    history = load_history(user_id)
    history[f"{account_user_id}_{match_id}"] = {'sent_at': time.strftime('%Y-%m-%d %H:%M:%S')}
    save_history(history, user_id)

def has_message_sent(user_id, account_user_id, match_id):
    history = load_history(user_id)
    return f"{account_user_id}_{match_id}" in history

# ============================================================
# TINDER API
# ============================================================

sessions = {}

def get_or_create_session(user_id):
    if user_id not in sessions:
        sessions[user_id] = {
            'app_session_id': str(uuid.uuid4()).upper(),
            'user_session_id': str(uuid.uuid4()).upper(),
            'created_at': time.time(),
            'request_count': 0,
            'app_session_time_base': random.uniform(2000, 2500),
            'user_session_time_base': random.uniform(600, 650),
        }
    session = sessions[user_id]
    session['request_count'] += 1
    if session['request_count'] > random.randint(50, 100):
        sessions[user_id] = {
            'app_session_id': str(uuid.uuid4()).upper(),
            'user_session_id': str(uuid.uuid4()).upper(),
            'created_at': time.time(),
            'request_count': 0,
            'app_session_time_base': random.uniform(2000, 2500),
            'user_session_time_base': random.uniform(600, 650),
        }
        session = sessions[user_id]
    return session

def build_headers(account, include_content_type=False):
    session = get_or_create_session(account['user_id'])
    elapsed = time.time() - session['created_at']
    app_session_time  = session['app_session_time_base']  + elapsed
    user_session_time = session['user_session_time_base'] + elapsed

    headers = {
        'x-auth-token': account['token'],
        'accept': 'application/json',
        'user-agent': f"Tinder/{account.get('tinder_version','17.3.0')} (iPhone; iOS {account.get('ios_version','18,4,3')}; Scale/2.00)",
        'tinder-version': account.get('tinder_version', '17.3.0'),
        'app-version': account.get('app_version', '6630'),
        'platform': 'ios',
        'accept-language': 'fr-FR,fr;q=0.9',
        'accept-encoding': 'gzip, deflate, br',
        'x-supported-image-formats': 'webp, jpeg',
        'x-device-ram': '1',
        'persistent-device-id': account['persistent_device_id'],
        'app-session-id': session['app_session_id'],
        'user-session-id': session['user_session_id'],
        'x-hubble-entity-id': str(uuid.uuid4()),
        'os-version': '00000000000',
        'app-session-time-elapsed': str(app_session_time),
        'user-session-time-elapsed': str(user_session_time),
    }
    if include_content_type:
        headers['content-type'] = 'application/json'
    return headers

def make_request(method, url, headers, proxies=None, json_data=None, data=None, timeout=15):
    # Toujours essayer curl_cffi en premier si disponible
    if CURL_CFFI_AVAILABLE:
        try:
            if method == 'GET':
                return curl_requests.get(
                    url, headers=headers, proxies=proxies,
                    timeout=timeout, impersonate="safari15_5", verify=False
                )
            elif method == 'POST':
                return curl_requests.post(
                    url, headers=headers, json=json_data, data=data,
                    proxies=proxies, timeout=timeout,
                    impersonate="safari15_5", verify=False
                )
        except Exception as e:
            print(f"[curl_cffi] {method} {url} failed: {e}")
            # Si curl_cffi échoue avec un proxy, ne pas retry sans proxy
            if proxies:
                raise Exception(f"Proxy injoignable: {e}")

    # Fallback requests standard — seulement sans proxy SOCKS5
    if proxies and any('socks' in str(v).lower() for v in proxies.values()):
        raise Exception("SOCKS5 proxy requires curl_cffi — install it properly")

    try:
        if method == 'GET':
            return requests.get(
                url, headers=headers, proxies=proxies,
                timeout=timeout, verify=False
            )
        elif method == 'POST':
            return requests.post(
                url, headers=headers, json=json_data, data=data,
                proxies=proxies, timeout=timeout, verify=False
            )
    except Exception as e:
        raise Exception(f"Request failed: {e}")

def generate_content_hash():
    import hashlib, base64, string
    random_str = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    hash_bytes = hashlib.sha256(random_str.encode()).digest()
    return base64.b64encode(hash_bytes).decode('utf-8').rstrip('=')

def tinder_check_token(account, proxies=None):
    headers = build_headers(account)
    try:
        resp = make_request('GET', 'https://api.gotinder.com/v2/profile?include=user', headers, proxies=proxies)
        if resp.status_code == 200:
            user = resp.json().get('data', {}).get('user', {})
            photos = user.get('photos', [])
            photo_url = photos[0].get('url', '') if photos else ''
            return {
                'valid': True,
                'name': user.get('name', 'N/A'),
                'user_id': user.get('_id', 'N/A'),
                'bio': user.get('bio', ''),
                'photo': photo_url,
                'age': user.get('age', ''),
            }
        return {'valid': False, 'error': f"HTTP {resp.status_code}"}
    except Exception as e:
        return {'valid': False, 'error': str(e)}

def tinder_init_session(account, proxies=None):
    h = build_headers(account, include_content_type=True)
    base = "https://api.gotinder.com"
    make_request('POST', f"{base}/v2/buckets", h, proxies=proxies, json_data={"experiments": [], "device_id": account.get('device_id', '')})
    time.sleep(random.uniform(0.3, 0.6))
    make_request('POST', f"{base}/v1/loc/init", build_headers(account, True), proxies=proxies, json_data={"deviceTime": int(time.time()*1000), "eventId": str(uuid.uuid4()).upper()})
    time.sleep(random.uniform(0.3, 0.6))
    make_request('POST', f"{base}/v2/meta", build_headers(account, True), proxies=proxies, json_data={"lon": account.get('longitude',2.3522), "lat": account.get('latitude',48.8566), "background": False, "force_fetch_resources": True})
    time.sleep(random.uniform(0.3, 0.6))
    make_request('GET', f"{base}/v2/profile?include=tutorials,spotify,user,offerings,boost,likes", build_headers(account), proxies=proxies)
    time.sleep(random.uniform(0.3, 0.6))
    make_request('GET', f"{base}/v2/fast-match/teaser?type=recently-active", build_headers(account), proxies=proxies)
    time.sleep(random.uniform(0.5, 1.0))
    return {'success': True}

def tinder_get_fast_match_count(account, proxies=None):
    headers = build_headers(account)
    try:
        resp = make_request('GET', 'https://api.gotinder.com/v2/fast-match/count', headers, proxies=proxies)
        if resp.status_code == 200:
            return {'success': True, 'count': resp.json().get('data', {}).get('count', 0)}
        return {'success': False, 'count': 0}
    except:
        return {'success': False, 'count': 0}

def tinder_get_profiles(account, count, proxies=None):
    all_profiles = []
    while len(all_profiles) < count:
        headers = build_headers(account)
        headers['support-short-video'] = '1'
        headers['connection-type'] = 'wifi'
        headers['connection-speed'] = '0.0'
        headers['x-request-id'] = str(uuid.uuid4()).upper()
        try:
            resp = make_request('GET', 'https://api.gotinder.com/v2/recs/core?locale=fr&duos=1&distance_setting=km', headers, proxies=proxies, timeout=15)
            if resp.status_code == 200:
                results = resp.json().get('data', {}).get('results', [])
                if not results:
                    break
                for item in results:
                    if item.get('type') == 'user':
                        all_profiles.append(item.get('user', {}))
                if len(all_profiles) < count:
                    time.sleep(random.uniform(2, 4))
            elif resp.status_code == 401:
                return {'success': False, 'error': 'BANNED', 'profiles': []}
            else:
                return {'success': False, 'error': f"HTTP {resp.status_code}", 'profiles': []}
        except Exception as e:
            return {'success': False, 'error': str(e), 'profiles': []}
    return {'success': True, 'profiles': all_profiles[:count]}

def tinder_swipe_like(account, target_id, proxies=None):
    headers = build_headers(account, include_content_type=True)
    body = {"content_hash": generate_content_hash(), "s_number": str(int(time.time()*1000000))}
    try:
        resp = make_request('POST', f"https://api.gotinder.com/like/{target_id}", headers, proxies=proxies, json_data=body)
        if resp.status_code == 200:
            data = resp.json()
            return {'success': True, 'is_match': data.get('match', False)}
        return {'success': False, 'error': f"HTTP {resp.status_code}"}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def tinder_swipe_pass(account, target_id, proxies=None):
    headers = build_headers(account, include_content_type=True)
    body = {"content_hash": generate_content_hash(), "s_number": str(int(time.time()*1000000))}
    try:
        resp = make_request('POST', f"https://api.gotinder.com/pass/{target_id}", headers, proxies=proxies, json_data=body)
        return {'success': resp.status_code == 200}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def tinder_get_matches(account, count=60, proxies=None):
    headers = build_headers(account)
    try:
        resp = make_request('GET', f"https://api.gotinder.com/v2/matches?include_conversations=true&message=0&count={count}", headers, proxies=proxies)
        if resp.status_code == 200:
            return {'success': True, 'matches': resp.json().get('data', {}).get('matches', [])}
        return {'success': False, 'error': f"HTTP {resp.status_code}"}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def tinder_get_conversations(account, count=60, proxies=None):
    headers = build_headers(account)
    try:
        resp = make_request('GET', f"https://api.gotinder.com/v2/matches?count={count}&message=1&page_size=100&is_tinder_u=false", headers, proxies=proxies)
        if resp.status_code == 200:
            matches = resp.json().get('data', {}).get('matches', [])
            return {'success': True, 'conversations': [m for m in matches if m.get('messages', [])]}
        return {'success': False, 'error': f"HTTP {resp.status_code}"}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def tinder_send_message(account, match_id, message_text, proxies=None):
    headers = build_headers(account, include_content_type=True)
    try:
        body = {
            "message": message_text,
            "matchId": match_id,
            "userId": account['user_id'],
            "otherId": match_id.split('-')[1] if '-' in match_id else match_id,
            "tempMessageId": str(int(time.time() * 1000)),
        }
        resp = make_request('POST', f"https://api.gotinder.com/user/matches/{match_id}", headers, proxies=proxies, json_data=body)
        print(f"[SEND] status={resp.status_code} body={resp.text[:300]}")
        if resp.status_code == 200:
            data = resp.json()
            if data.get('_id') or data.get('sent_date') or data.get('message'):
                return {'success': True}
            else:
                print(f"[SEND] 200 mais réponse vide/inattendue: {data}")
                return {'success': True}
        return {'success': False, 'error': f"HTTP {resp.status_code}", 'details': resp.text[:200]}
    except Exception as e:
        print(f"[SEND] exception: {e}")
        return {'success': False, 'error': str(e)}

def tinder_get_messages(account, match_id, proxies=None):
    headers = build_headers(account)
    try:
        resp = make_request('GET', f"https://api.gotinder.com/v2/matches/{match_id}/messages?count=100", headers, proxies=proxies)
        if resp.status_code == 200:
            messages = resp.json().get('data', {}).get('messages', [])
            messages.sort(key=lambda m: m.get('sent_date', ''))
            return {'success': True, 'messages': messages}
        return {'success': False, 'messages': []}
    except Exception as e:
        return {'success': False, 'messages': []}

def tinder_update_bio(account, bio, proxies=None):
    headers = build_headers(account, include_content_type=True)
    try:
        # Forcer requests standard avec PySocks pour SOCKS5
        import requests as req
        resp = req.post(
            'https://api.gotinder.com/v2/profile/user',
            headers=headers,
            json={"bio": bio},
            proxies=proxies,
            timeout=20,
            verify=False
        )
        return {
            'success': resp.status_code == 200,
            'error': f"HTTP {resp.status_code}" if resp.status_code != 200 else None
        }
    except Exception as e:
        return {'success': False, 'error': str(e)}

# ============================================================
# IA
# ============================================================

OPENAI_API_KEY = "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"
OPENAI_MODEL   = "gpt-4.1-mini"

PERSONA = """
Tu es Sarah, 19 ans, étudiante en communication, sur Tinder.

═══ PERSONNALITÉ ═══
- Détachée mais accessible. L'autre doit faire un minimum d'effort.
- Taquine, naturelle, spontanée. Jamais froide, jamais trop enthousiaste.
- Ton chill, décontracté. Ni cordial ni professionnel.

═══ ÉCRITURE OBLIGATOIRE ═══
- PAS de majuscule en début de phrase. PAS de point final. Style SMS.
- Mots : mdr, genre, jsp, trop, grave, ptdr, jpp, tfk.
- Français correct. JAMAIS "quoi est ton" → écrire "c'est quoi ton" ou "t'as".
- Émojis : max 1 tous les 3-4 messages, à la fin uniquement.
- Réponses courtes : 6-20 mots en général.

═══ CONVERSATION ═══
- Lis TOUT l'historique. Réponds de façon COHÉRENTE avec ce qu'il vient de dire.
- Max 2 questions d'affilée, sinon alterne remarques/affirmations.
- JAMAIS finir par une réponse fermée. TOUJOURS une question ou relance.
- "ça va bien" seul = INTERDIT. Toujours [réponse] + question.

═══ RELANCE ═══
- S'il a DÉJÀ répondu (tranquille, ça va, ouais) → NE PAS redemander "et toi ?". PIVOTE.
- "écoute" / "tranquille écoute" = il va parler → invite-le à continuer.

═══ CAS SPÉCIAUX ═══
- Méfiance / "t'es fake" / "tu cherches des abonnés" → DÉSAMORCE avec humour. JAMAIS confirmer. JAMAIS mentionner lntsa dans ce cas.
- Insulte / message vulgaire → réponds avec humour léger ou ignore, reste chill.
- Media (gif, image) → ne commente pas le contenu que tu ne vois pas. Relance sur autre chose.
- Langue anglaise détectée → réponds en anglais avec le même ton décontracté.

═══ LOCALISATION ═══
- JAMAIS d'adresse, ville, bar ou lieu inventé.
- Esquive avec humour : "jsuis pas loin", "un peu de mystère", "tu veux mon adresse aussi ?"

═══ LNTSA - Objectif ═══
- Écris exactement "lntsa" (L-n-t-s-a). PAS "insta", PAS "lnsta". Pseudo SANS @.
- Snap/WhatsApp/numéro → REFUSE toujours, propose lntsa UNIQUEMENT.
- Quand il propose de partir ailleurs → lntsa DIRECTEMENT, pas "lntsa ou snap ?".
"""


def _call_openai(prompt, max_tokens=100):
    if not OPENAI_API_KEY or OPENAI_API_KEY == "REMPLACE_PAR_TA_CLE_OPENAI":
        print("⚠️  Clé OpenAI non configurée")
        return None
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": OPENAI_MODEL, "messages": [{"role": "user", "content": prompt}],
                  "temperature": 0.9, "max_tokens": max_tokens},
            timeout=30
        )
        if resp.status_code == 200:
            reply = resp.json()['choices'][0]['message']['content'].strip().strip('"').strip("'")
            for prefix in ['réponse:', 'response:', 'message:', 'sarah:']:
                if reply.lower().startswith(prefix):
                    reply = reply[len(prefix):].strip()
            reply = reply.replace('Lntsa', 'lntsa').replace('LNTSA', 'lntsa')
            reply = reply.replace('Insta', 'lntsa').replace('insta', 'lntsa').replace('INSTA', 'lntsa')
            reply = reply.replace('lnsta', 'lntsa').replace('lsnta', 'lntsa')
            reply = reply.replace('quoi est ton', "c'est quoi ton").replace('quoi est ta', "c'est quoi ta")
            reply = reply.replace('Instagram', 'lntsa').replace('instagram', 'lntsa')
            return reply
        else:
            print(f"⚠️  OpenAI {resp.status_code}: {resp.text[:200]}")
            return None
    except Exception as e:
        print(f"⚠️  OpenAI exception: {e}")
        return None


def generate_ai_reply(conversation_history, match_name, match_bio, username, social_network):
    our_messages   = [m for m in conversation_history if m['sender'] == 'NOUS']
    their_messages = [m for m in conversation_history if m['sender'] != 'NOUS']

    if not their_messages:
        opener_prompt = f"""{PERSONA}
C'est un tout nouveau match, aucun message échangé.
Son nom: {match_name}
{"Sa bio: " + match_bio if match_bio else "Pas de bio."}
Envoie un premier message d'accroche court et naturel.
JAMAIS "coucou ça va ?". Quelque chose de taquin ou original.
Max 10 mots, pas de guillemets, pas de point final."""
        return _call_openai(opener_prompt, max_tokens=60)

    already_redirected = False
    soft_hint_given    = False
    soft_hint_markers = ['jamais sur tinder', 'jamais ici', "j'me perds", 'notifs',
                          'tinder pour', 'ici pour', 'jamais là', "pas trop l'habitude",
                          'parler bcp sur tinder', "pas trop présente", "j'check pas",
                          "longues discu sur tinder", "longues discu ici"]
    if username:
        for msg in our_messages:
            ml = msg['text'].lower()
            if username.lower() in ml:
                already_redirected = True
                break
            if any(hint in ml for hint in soft_hint_markers):
                soft_hint_given = True

    if already_redirected:
        return "__CTA_SENT__"

    formatted = "\n".join(
        f"TOI (Sarah): {m['text']}" if m['sender'] == 'NOUS' else f"LUI ({m['sender']}): {m['text']}"
        for m in conversation_history[-10:]
    )
    total_exchanges = min(len(our_messages), len(their_messages))
    last_their_msg  = their_messages[-1]['text']
    lml             = last_their_msg.lower()

    he_proposes_insta  = 'insta' in lml or 'instagram' in lml
    he_proposes_snap   = 'snap' in lml or 'snapchat' in lml
    he_proposes_social = he_proposes_insta or he_proposes_snap or any(
        w in lml for w in ['whatsapp', 'telegram', 'numero', 'numéro', 'appel', 'tel'])

    def detect_pseudo_given(msg_text, history):
        detection_prompt = f"""Analyse ce message dans le contexte de la conversation.
Historique récent:
{chr(10).join(f"{'NOUS' if m['sender'] == 'NOUS' else m['sender']}: {m['text']}" for m in history[-4:])}

Message à analyser: "{msg_text}"

Est-ce que cette personne donne son pseudo Instagram/réseau social dans ce message ?
Réponds UNIQUEMENT par "oui" ou "non"."""
        result = _call_openai(detection_prompt, max_tokens=5)
        return result and result.strip().lower().startswith('oui')

    he_gave_his_pseudo = detect_pseudo_given(last_their_msg, conversation_history)

    flirty_words      = ['croque','canon','magnifique','splendide','sexy','bombe',
                         'dingue','charmante','hot','🔥','😍','❤️']
    compliment_phrases= ["t'es belle","tu es belle","t'es canon","trop belle",
                         "trop mignonne","t'es mignonne","tu es mignonne","vraiment jolie","trop jolie"]
    is_flirty    = any(w in lml for w in flirty_words)
    is_compliment= is_flirty or any(p in lml for p in compliment_phrases)
    is_question  = '?' in last_their_msg

    direct_words = ['envie','date','sortir','voir','rencontrer','rdv','ce soir',
                    'week-end','weekend','dispo','disponible','on se voit','verre','resto']
    is_direct    = any(w in lml for w in direct_words)

    skeptical_words = ['fake','bot','vraie','réelle','arnaque','followers',
                       'follow','abonnés','promo','pub','gratter']
    is_skeptical = any(w in lml for w in skeptical_words)

    location_kw  = ["d'où","d ou",'où tu','ville','habite','vis où','viens','secteur',
                    'coin','region',"t'habite",'tu habites','habite ou','quel bar',
                    'quel parc','où ça',"c'est où",'ou ca','quel coin','dans quel','ou habites']
    he_asked_location = any(kw in lml for kw in location_kw) or ('où' in lml and len(lml) < 35)

    job_kw       = ['fais quoi','travail','boulot','métier','études','taff','bosses']
    he_asked_job = any(kw in lml for kw in job_kw) and is_question

    he_asked_et_toi = "et toi" in lml
    he_asked_cava   = any(p in lml for p in ['ça va','ca va','comment tu vas',
                                              'comment ça va','tu vas bien','comment vas-tu'])
    short_positive  = (len(last_their_msg.split()) <= 4 and
                       any(w in lml for w in ['tranquille','ça va','ca va','ouais','oui ','bien','nickel']))

    confusion_phrases = ['comment ça','comment ca','hein ?','hein ','je comprends pas',
                         'comprend pas',"j'ai pas compris",'compris quoi']
    he_is_confused  = (len(last_their_msg) < 40 and
                       any(p in lml for p in confusion_phrases) and
                       not any(q in lml for q in ['de quoi','quoi comme','quoi tu','quoi elle']))

    q_already_answered = False
    if is_question:
        q_words = ['fais quoi','tu fais','travail','bosses','étudies','études','comm','habite','où']
        if any(q in lml for q in q_words):
            for msg in our_messages:
                ml2 = msg['text'].lower()
                if (('comm' in ml2 or 'fac' in ml2 or 'étudiante' in ml2) and
                        any(q in lml for q in ['fais quoi','tu fais','travail','bosses'])):
                    q_already_answered = True; break
                if (('paris' in ml2 or 'lyon' in ml2 or 'habite' in ml2) and
                        any(q in lml for q in ['habite','où','ville'])):
                    q_already_answered = True; break

    if total_exchanges >= 12:
        full_redirect_prob, soft_hint_prob = 1.0, 0.0
    elif total_exchanges >= 10:
        full_redirect_prob = 0.85 if soft_hint_given else 0.3
        soft_hint_prob     = 0.0  if soft_hint_given else 0.4
    elif total_exchanges >= 8:
        full_redirect_prob = 0.6  if soft_hint_given else 0.15
        soft_hint_prob     = 0.0  if soft_hint_given else 0.5
    elif total_exchanges >= 6:
        full_redirect_prob = 0.4  if soft_hint_given else 0.0
        soft_hint_prob     = 0.45
    elif total_exchanges >= 5:
        full_redirect_prob, soft_hint_prob = 0.0, 0.35
    else:
        full_redirect_prob, soft_hint_prob = 0.0, 0.0

    should_soft_hint = (not soft_hint_given and username and random.random() < soft_hint_prob)
    should_redirect  = (username and random.random() < full_redirect_prob and
                        (soft_hint_given or total_exchanges >= 11))

    p = PERSONA

    greeting_words   = ['salut','hello','hey','coucou','bonjour','cc','slt','hi','yo','wesh']
    is_simple_greeting = (any(lml.startswith(w) or lml == w for w in greeting_words) and
                          len(last_their_msg.split()) <= 5 and
                          total_exchanges == 0 and not (is_compliment or is_flirty))

    if short_positive and not he_asked_cava:
        prompt = f"""{p}
{match_name} a répondu court : "{last_their_msg}"
Historique:\n{formatted}
Il a DÉJÀ répondu. NE REDEMANDE PAS "et toi ?". PIVOTE vers autre chose.
6-12 mots, pas de guillemets."""

    elif he_asked_cava:
        prompt = f"""{p}
{match_name} demande comment tu vas: "{last_their_msg}"
Historique:\n{formatted}
Réponds PUIS relance. JAMAIS "ça va bien merci" seul.
6-15 mots, 1 emoji max, pas de guillemets."""
    elif is_simple_greeting:
        prompt = f"""{p}
{match_name} te dit bonjour: "{last_their_msg}"
Style détaché mais accessible. Court.
4-8 mots max, pas de guillemets."""

    elif he_gave_his_pseudo:
        prompt = f"""{p}
{match_name} vient de donner son pseudo en réponse à ta demande.
Historique:\n{formatted}
Réponds en confirmant que tu vas l'ajouter ET donne TON pseudo {username} sur lntsa.
OBLIGATOIRE : mentionner "lntsa" ET "{username}" dans le message.
12-18 mots, PAS de guillemets."""

    elif he_proposes_insta:
        prompt = f"""{p}
{match_name} te propose Instagram ou donne son pseudo. PARFAIT !
Historique:\n{formatted}
Réponds en donnant TON pseudo {username} directement.
OBLIGATOIRE : écrire "{username}" ET "lntsa" dans le message.
8-15 mots, PAS de guillemets."""
    elif he_proposes_snap:
        prompt = f"""{p}
{match_name} demande ton snap: "{last_their_msg}"
Historique:\n{formatted}
REFUSE snap. Propose lntsa : "t'as lntsa ? moi c'est {username}".
12-25 mots, écris "lntsa", pas de guillemets."""

    elif he_proposes_social:
        prompt = f"""{p}
{match_name} propose WhatsApp/numéro: "{last_their_msg}"
Historique:\n{formatted}
REFUSE. Propose lntsa UNIQUEMENT : "t'as lntsa ? moi c'est {username}".
15-25 mots, écris "lntsa", pas de guillemets."""

    elif is_skeptical:
        prompt = f"""{p}
{match_name} semble méfiant: "{last_their_msg}"
Historique:\n{formatted}
Rassure avec humour. Ne mentionne PAS lntsa.
15-25 mots, pas de guillemets."""

    elif is_direct and total_exchanges >= 8:
        prompt = f"""{p}
{match_name} propose un date: "{last_their_msg}"
Historique:\n{formatted}
Dis OUI, explique qu'il faut s'organiser ailleurs, propose lntsa ({username}).
22-38 mots, écris "lntsa", pas de guillemets."""

    elif is_compliment or is_flirty:
        prompt = f"""{p}
{match_name} te fait un compliment: "{last_their_msg}"
Historique:\n{formatted}
Réagis au compliment puis RELANCE avec une question.
8-18 mots, 1 emoji max, pas de guillemets."""

    elif he_asked_location:
        prompt = f"""{p}
{match_name} demande ta localisation: "{last_their_msg}"
Historique:\n{formatted}
NE DONNE JAMAIS de lieu. Esquive avec humour.
10-20 mots, pas de guillemets."""

    elif he_asked_job:
        prompt = f"""{p}
{match_name} demande ton job: "{last_their_msg}"
Historique:\n{formatted}
Réponds (étudiante en comm) et retourne la question.
10-18 mots, pas de guillemets."""

    elif he_asked_et_toi:
        prompt = f"""{p}
{match_name} dit "et toi ?": "{last_their_msg}"
Historique:\n{formatted}
RÉPONDS à la question puis RELANCE. Finis par une question.
10-18 mots, pas de guillemets."""

    elif he_is_confused:
        prompt = f"""{p}
{match_name} comprend pas: "{last_their_msg}"
Historique:\n{formatted}
Reformule ou invite-le à continuer.
8-15 mots, pas de guillemets."""

    elif q_already_answered:
        prompt = f"""{p}
{match_name} repose une question déjà répondue: "{last_their_msg}"
Historique:\n{formatted}
Rappelle brièvement et PIVOTE.
10-18 mots, pas de guillemets."""

    elif should_soft_hint:
        prompt = f"""{p}
Conversation avec {match_name}. Plante la graine (sans mentionner lntsa).
Son message: "{last_their_msg}"
Historique:\n{formatted}
Réagis PUIS glisse "par contre"/"sinon"/"au fait" + phrase douce sur tinder/notifs.
INTERDIT: lntsa, insta, pseudo. 15-25 mots."""

    elif should_redirect:
        prompt = f"""{p}
Conversation avec {match_name}. Graine plantée, propose maintenant lntsa.
Son message: "{last_their_msg}"
Historique:\n{formatted}
[réagir au message] + "t'as lntsa ? moi c'est {username}".
20-35 mots, écris "lntsa", pas de guillemets."""

    else:
        prompt = f"""{p}
Historique:\n{formatted}
Il dit: "{last_their_msg}"
Réponds DÉCONTRACTÉ, NATUREL. Finis TOUJOURS par une question.
6-15 mots, pas de guillemets, 1 emoji max ou pas."""

    if len(their_messages) == 1:
        prompt += "\n\n⚠️ PREMIER MESSAGE: finir OBLIGATOIREMENT par une question ouverte."

    return _call_openai(prompt, max_tokens=100)


# ============================================================
# AUTOMATION SCHEDULER
# ============================================================

automation_jobs = {}
automation_threads = {}

def run_automation_task(task_id, task, user_id):
    import datetime
    automation_jobs[task_id]['status'] = 'running'
    automation_jobs[task_id]['log'] = []

    def log(msg):
        automation_jobs[task_id]['log'].append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")
        if len(automation_jobs[task_id]['log']) > 500:
            automation_jobs[task_id]['log'] = automation_jobs[task_id]['log'][-500:]

    interval_sec = int(task.get('interval_minutes', 30)) * 60
    task_type = task.get('type', 'massdm')
    parallel  = task.get('parallel', False)

    log(f"⚡ Tâche démarrée — {task_type} toutes les {task.get('interval_minutes')}min")

    while automation_jobs.get(task_id, {}).get('status') == 'running':
        next_run = time.time() + interval_sec
        automation_jobs[task_id]['next_run']     = next_run
        automation_jobs[task_id]['next_run_str'] = datetime.datetime.fromtimestamp(next_run).strftime('%H:%M:%S')
        log(f"🔁 Exécution cycle — {task_type}")

        try:
            job_id      = str(uuid.uuid4())[:8]
            account_ids = []

            if task_type in ('massdm', 'chatting'):
                username       = task.get('username', '')
                social_network = task.get('social_network', 'Instagram')
                mode           = task_type
                t = threading.Thread(target=run_mass_dm,
                    args=(job_id, account_ids, username, social_network, mode, user_id), daemon=True)
                t.start()
                while t.is_alive():
                    if automation_jobs.get(task_id, {}).get('status') != 'running': break
                    job_logs      = dm_progress.get(job_id, {}).get('log', [])
                    already_synced = automation_jobs[task_id].get('_dm_synced', 0)
                    for entry in job_logs[already_synced:]:
                        automation_jobs[task_id]['log'].append(
                            f"[{datetime.datetime.now().strftime('%H:%M:%S')}]   {entry}")
                    automation_jobs[task_id]['_dm_synced'] = len(job_logs)
                    time.sleep(1)
                t.join()
                sent    = dm_progress.get(job_id, {}).get('total_sent', 0)
                skipped = dm_progress.get(job_id, {}).get('total_skipped', 0)
                log(f"✅ Cycle terminé — {sent} envoyés, {skipped} ignorés")

            elif task_type in ('swipe', 'forcematch'):
                swipe_count = int(task.get('swipe_count', 50))
                like_pct    = int(task.get('like_pct', 80))
                mode        = 'forcematch' if task_type == 'forcematch' else 'basic'
                t = threading.Thread(target=run_auto_swipe,
                    args=(job_id, account_ids, swipe_count, like_pct, mode, user_id, parallel), daemon=True)
                t.start()
                while t.is_alive():
                    if automation_jobs.get(task_id, {}).get('status') != 'running': break
                    job_logs       = swipe_progress.get(job_id, {}).get('log', [])
                    already_synced = automation_jobs[task_id].get('_sw_synced', 0)
                    for entry in job_logs[already_synced:]:
                        automation_jobs[task_id]['log'].append(
                            f"[{datetime.datetime.now().strftime('%H:%M:%S')}]   {entry}")
                    automation_jobs[task_id]['_sw_synced'] = len(job_logs)
                    time.sleep(1)
                t.join()
                likes   = swipe_progress.get(job_id, {}).get('total_likes', 0)
                matches = swipe_progress.get(job_id, {}).get('total_matches', 0)
                log(f"✅ Cycle terminé — {likes} likes, {matches} matchs")

            record_daily_stats(user_id)
        except Exception as e:
            log(f"❌ Erreur: {str(e)}")

        log(f"⏳ Prochain cycle dans {task.get('interval_minutes')}min")
        elapsed = 0
        while elapsed < interval_sec:
            if automation_jobs.get(task_id, {}).get('status') != 'running': break
            time.sleep(5)
            elapsed += 5

    automation_jobs[task_id]['status'] = 'stopped'
    log("🛑 Tâche arrêtée")

match_count_cache = {}
swipe_progress    = {}

def run_auto_swipe(job_id, account_ids, swipe_count, like_pct, mode, user_id, parallel=False):
    accounts = load_accounts(user_id)
    accounts = [a for a in accounts if a['user_id'] in account_ids] if account_ids else accounts

    swipe_progress[job_id] = {
        'status': 'running',
        'total_accounts': len(accounts),
        'completed_accounts': 0,
        'total_likes': 0, 'total_dislikes': 0,
        'total_matches': 0, 'total_failed': 0,
        'accounts': [], 'log': [], 'parallel': parallel,
    }

    lock = threading.Lock()

    def log(msg):
        with lock:
            swipe_progress[job_id]['log'].append(msg)

    def mark_banned(account):
        with lock:
            all_accs = load_accounts(user_id)
            for a in all_accs:
                if a['user_id'] == account['user_id']:
                    a['_alive'] = False
            save_accounts(all_accs, user_id)

    def process_account(account):
        # Proxy spécifique au compte ou proxy global
        proxies = get_proxies_for_account(account, user_id)
        proxy_label = f"[proxy: {account.get('proxy_url','global')[:30]}...]" if account.get('proxy_enabled') and account.get('proxy_url') else "[proxy: global]" if proxies else "[no proxy]"
        log(f"▶ Démarrage {account['name']} {proxy_label}")
        # Vérification IP réelle
        real_ip = get_current_ip(proxies)
        if real_ip:
            log(f"  🌐 IP réelle : {real_ip} {'✅ proxy actif' if proxies else '⚠️ pas de proxy'}")
        else:
            log(f"  ❌ IP non vérifiable — proxy injoignable ?")
        tinder_init_session(account, proxies)
        time.sleep(random.uniform(1, 2))
        wly = tinder_get_fast_match_count(account, proxies).get('count', 0)

        likes = dislikes = matches = failed = 0

        if mode == 'forcematch':
            for cycle in range(1, swipe_count + 1):
                discover = tinder_get_profiles(account, 2, proxies)
                if not discover['success']:
                    if discover.get('error') == 'BANNED':
                        log(f"  🚫 {account['name']} — COMPTE BANNI / TOKEN EXPIRÉ !")
                        mark_banned(account)
                        break
                    failed += 1
                    continue
                if len(discover['profiles']) < 2:
                    failed += 1
                    continue
                p = discover['profiles']
                tinder_swipe_pass(account, p[0]['_id'], proxies)
                time.sleep(random.uniform(1.5, 3))
                if random.random() < (like_pct / 100):
                    r = tinder_swipe_like(account, p[1]['_id'], proxies)
                    if r['success']:
                        likes += 1
                        if r.get('is_match'): matches += 1
                    else:
                        failed += 1
                else:
                    tinder_swipe_pass(account, p[1]['_id'], proxies)
                    dislikes += 1
                time.sleep(random.uniform(1.5, 3))
                tinder_init_session(account, proxies)
                time.sleep(random.uniform(3, 6))
                log(f"  {account['name']} — cycle {cycle}/{swipe_count}")
        else:
            discover = tinder_get_profiles(account, swipe_count, proxies)
            if not discover['success']:
                if discover.get('error') == 'BANNED':
                    log(f"  🚫 {account['name']} — COMPTE BANNI / TOKEN EXPIRÉ !")
                    mark_banned(account)
                else:
                    failed = swipe_count
            else:
                for profile in discover['profiles']:
                    tid = profile.get('_id')
                    if not tid:
                        failed += 1
                        continue
                    if random.random() < (like_pct / 100):
                        r = tinder_swipe_like(account, tid, proxies)
                        if r['success']:
                            likes += 1
                            if r.get('is_match'): matches += 1
                        else:
                            failed += 1
                    else:
                        r = tinder_swipe_pass(account, tid, proxies)
                        if r['success']: dislikes += 1
                        else: failed += 1
                    time.sleep(random.uniform(1.3, 3.4))
                    log(f"  {account['name']} — {likes+dislikes}/{swipe_count}")

        acc_result = {'name': account['name'], 'wly': wly,
                      'likes': likes, 'dislikes': dislikes, 'matches': matches, 'failed': failed}
        with lock:
            swipe_progress[job_id]['accounts'].append(acc_result)
            swipe_progress[job_id]['total_likes']    += likes
            swipe_progress[job_id]['total_dislikes'] += dislikes
            swipe_progress[job_id]['total_matches']  += matches
            swipe_progress[job_id]['total_failed']   += failed
            swipe_progress[job_id]['completed_accounts'] += 1
        log(f"✅ {account['name']} — {likes}L / {dislikes}D / {matches}M")

    if parallel and len(accounts) > 1:
        log(f"⚡ Mode parallèle — {len(accounts)} comptes simultanés")
        threads = [threading.Thread(target=process_account, args=(a,), daemon=True) for a in accounts]
        for t in threads: t.start()
        for t in threads: t.join()
    else:
        for account in accounts:
            process_account(account)

    stats = load_stats(user_id)
    stats['swipes']  += swipe_progress[job_id]['total_likes'] + swipe_progress[job_id]['total_dislikes']
    stats['matches'] += swipe_progress[job_id]['total_matches']
    save_stats(stats, user_id)
    record_daily_stats(user_id)

    all_accounts = load_accounts(user_id)
    for acc_result in swipe_progress[job_id]['accounts']:
        for a in all_accounts:
            if a['name'] == acc_result['name']:
                a['total_likes']   = a.get('total_likes', 0)   + acc_result.get('likes', 0)
                a['total_matches'] = a.get('total_matches', 0) + acc_result.get('matches', 0)
                break
    save_accounts(all_accounts, user_id)
    swipe_progress[job_id]['status'] = 'done'

dm_progress = {}

def run_mass_dm(job_id, account_ids, username, social_network, mode, user_id):
    accounts = load_accounts(user_id)
    accounts = [a for a in accounts if a['user_id'] in account_ids] if account_ids else accounts

    dm_progress[job_id] = {
        'status': 'running',
        'total_accounts': len(accounts), 'completed_accounts': 0,
        'total_sent': 0, 'total_replies': 0, 'total_cta': 0,
        'total_skipped': 0, 'total_failed': 0,
        'accounts': [], 'log': []
    }

    fallback_messages = [
        "Coucou, ça va ?",
        "Hey ! Comment tu vas ?",
        "Salut 😊",
        "Cc ! Tu vas bien ?",
    ]

    def log(msg):
        dm_progress[job_id]['log'].append(msg)

    for account in accounts:
        # Proxy spécifique au compte ou proxy global
        proxies = get_proxies_for_account(account, user_id)
        proxy_label = f"[proxy: {account.get('proxy_url','')[:25]}...]" if account.get('proxy_enabled') and account.get('proxy_url') else "[proxy: global]" if proxies else "[no proxy]"
        log(f"▶ Compte : {account['name']} {proxy_label}")
        real_ip = get_current_ip(proxies)
        if real_ip:
            log(f"  🌐 IP réelle : {real_ip} {'✅ proxy actif' if proxies else '⚠️ pas de proxy'}")
        else:
            log(f"  ❌ IP non vérifiable — proxy injoignable ?")
        tinder_init_session(account, proxies)
        time.sleep(random.uniform(1, 2))

        matches_r = tinder_get_matches(account, 60, proxies)
        convs_r   = tinder_get_conversations(account, 60, proxies)

        all_matches = matches_r.get('matches', [])
        if convs_r.get('success'):
            seen = {m['_id'] for m in all_matches}
            for c in convs_r['conversations']:
                if c['_id'] not in seen:
                    all_matches.append(c)
                    seen.add(c['_id'])

        sent = skipped = failed = replies = cta = 0

        for match in all_matches:
            match_id   = match.get('_id')
            match_name = match.get('person', {}).get('name', 'Inconnu')
            match_bio  = match.get('person', {}).get('bio', '')

            if not match_id:
                failed += 1
                continue

            hist_r   = tinder_get_messages(account, match_id, proxies)
            messages = hist_r.get('messages', [])

            last_sender      = None
            has_their_reply  = False
            conversation_history = []

            for msg in messages:
                sender_id = msg.get('from', '')
                text      = msg.get('message', '')
                if sender_id == account['user_id']:
                    sender_label = 'NOUS'
                    last_sender  = 'NOUS'
                else:
                    sender_label    = match_name
                    last_sender     = match_name
                    has_their_reply = True
                conversation_history.append({'sender': sender_label, 'text': text})

            if has_their_reply:
                replies += 1

            log(f"  ─── 💬 {match_name} ({len(conversation_history)} msg) ───")
            if conversation_history:
                for m in conversation_history:
                    prefix = "  → NOUS" if m['sender'] == 'NOUS' else f"  ← {match_name}"
                    log(f"  {prefix}: {m['text'][:80]}")
            else:
                log(f"  (aucun message — nouveau match)")

            if last_sender == 'NOUS':
                skipped += 1
                log(f"  ⏭ {match_name} — dernier msg = nous, on attend sa réponse")
                continue

            if not conversation_history and has_message_sent(user_id, account['user_id'], match_id):
                skipped += 1
                log(f"  ⏭ {match_name} — déjà contacté, pas de réponse")
                continue

            if mode == 'chatting':
                log(f"  🤖 Génération IA en cours...")
                msg_text = generate_ai_reply(conversation_history, match_name, match_bio, username, social_network)
                if msg_text == "__CTA_SENT__":
                    skipped += 1
                    log(f"  ⏭ {match_name} — CTA déjà envoyé, on attend")
                    continue
                if msg_text:
                    log(f"  🤖 IA → \"{msg_text}\"")
                else:
                    msg_text = random.choice(fallback_messages)
                    log(f"  ⚠️ IA échouée → Fallback: \"{msg_text}\"")

            elif mode == 'massdm':
                msg_text = random.choice([
                    f"Coucou, ton profil m'a fait sourire haha ! Je suis plus sur {social_network}, cherche {username} si tu veux qu'on parle 😊",
                    f"Salut ! J'utilise plus trop cette appli... Je suis {username} sur {social_network} 🙈",
                    f"Hey ! Par contre je réponds pas souvent ici, {username} sur {social_network} c'est mieux !",
                ])
            else:
                msg_text = random.choice(fallback_messages)

            if username and username.lower() in msg_text.lower():
                cta += 1

            result = tinder_send_message(account, match_id, msg_text, proxies)
            if result['success']:
                sent += 1
                mark_message_sent(user_id, account['user_id'], match_id)
                log(f"  ✅ Envoyé à {match_name}")
            else:
                failed += 1
                log(f"  ❌ {match_name} — {result.get('error')}")

            time.sleep(random.uniform(2, 5))

        acc_result = {'name': account['name'], 'sent': sent, 'skipped': skipped,
                      'failed': failed, 'replies': replies, 'cta': cta}
        dm_progress[job_id]['accounts'].append(acc_result)
        dm_progress[job_id]['total_sent']    += sent
        dm_progress[job_id]['total_replies']  = dm_progress[job_id].get('total_replies', 0) + replies
        dm_progress[job_id]['total_cta']      = dm_progress[job_id].get('total_cta', 0) + cta
        dm_progress[job_id]['total_skipped'] += skipped
        dm_progress[job_id]['total_failed']  += failed
        dm_progress[job_id]['completed_accounts'] += 1

    stats = load_stats(user_id)
    stats['messages'] += dm_progress[job_id]['total_sent']
    stats['replies']  += dm_progress[job_id].get('total_replies', 0)
    stats['cta_sent'] += dm_progress[job_id].get('total_cta', 0)
    save_stats(stats, user_id)
    record_daily_stats(user_id)
    dm_progress[job_id]['status'] = 'done'

# ============================================================
# ROUTES API
# ============================================================



def load_proxy_pool(user_id="default"):
    try:
        with open(PROXY_POOL_FILE, 'r') as f:
            return json.load(f).get(str(user_id), [])
    except:
        return []

def save_proxy_pool(pool, user_id="default"):
    try:
        with open(PROXY_POOL_FILE, 'r') as f:
            all_data = json.load(f)
    except:
        all_data = {}
    all_data[str(user_id)] = pool
    with open(PROXY_POOL_FILE, 'w') as f:
        json.dump(all_data, f, indent=2)

def pop_proxy_from_pool(user_id="default"):
    """Prend le premier proxy disponible et le retire du pool."""
    pool = load_proxy_pool(user_id)
    if not pool:
        return None
    proxy = pool.pop(0)
    save_proxy_pool(pool, user_id)
    return proxy

@app.route('/api/proxy-pool', methods=['GET'])
@require_auth
def get_proxy_pool():
    pool = load_proxy_pool(current_user_id())
    return jsonify({'success': True, 'pool': pool, 'count': len(pool)})

@app.route('/api/proxy-pool', methods=['POST'])
@require_auth
def set_proxy_pool():
    data = request.json or {}
    raw_list = data.get('proxies', [])
    # Nettoyer et formater chaque proxy
    cleaned = []
    for p in raw_list:
        p = p.strip()
        if not p:
            continue
        if not (p.startswith('http') or p.startswith('socks')):
            if '@' in p:
                p = f'socks5://{p}'
        if p:
            cleaned.append(p)
    save_proxy_pool(cleaned, current_user_id())
    return jsonify({'success': True, 'count': len(cleaned)})

@app.route('/api/proxy-pool/pop', methods=['POST'])
@require_auth
def pop_proxy():
    proxy = pop_proxy_from_pool(current_user_id())
    if not proxy:
        return jsonify({'success': False, 'error': 'Pool vide'})
    return jsonify({'success': True, 'proxy': proxy})

@app.route('/api/proxy-pool/add', methods=['POST'])
@require_auth
def add_to_proxy_pool():
    data = request.json or {}
    new_proxies = data.get('proxies', [])
    pool = load_proxy_pool(current_user_id())
    for p in new_proxies:
        p = p.strip()
        if not p:
            continue
        if not (p.startswith('http') or p.startswith('socks')):
            if '@' in p:
                p = f'socks5://{p}'
        if p and p not in pool:
            pool.append(p)
    save_proxy_pool(pool, current_user_id())
    return jsonify({'success': True, 'count': len(pool)})

@app.route('/api/proxy-pool/clear', methods=['POST'])
@require_auth
def clear_proxy_pool():
    save_proxy_pool([], current_user_id())
    return jsonify({'success': True})



# ── AUTH ──

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    users = load_users()
    for uid, u in users.items():
        if u['username'] == username and u['password'] == hash_password(password):
            token = generate_token()
            active_tokens[token] = {'user_id': uid, 'username': u['username'], 'role': u['role'], '_created': time.time()}
            with _tokens_lock:
                _save_tokens(active_tokens)

            return jsonify({'success': True, 'token': token, 'username': u['username'], 'role': u['role']})
    return jsonify({'success': False, 'error': 'Identifiants incorrects'}), 401

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    token = get_token_from_request()
    if token in active_tokens:
        del active_tokens[token]
        with _tokens_lock:
            _save_tokens(active_tokens)
    return jsonify({'success': True})

@app.route('/api/auth/me', methods=['GET'])
def me():
    token = get_token_from_request()
    if not token or token not in active_tokens:
        return jsonify({'success': False, 'authenticated': False})
    u = active_tokens[token]
    return jsonify({'success': True, 'authenticated': True, 'username': u.get('username'), 'role': u.get('role')})

@app.route('/api/auth/change-password', methods=['POST'])
@require_auth
def change_password():
    data  = request.json or {}
    old_pw = data.get('old_password', '')
    new_pw = data.get('new_password', '')
    if not new_pw or len(new_pw) < 6:
        return jsonify({'success': False, 'error': 'Mot de passe trop court (min 6 chars)'}), 400
    uid   = current_user_data().get('user_id')
    users = load_users()
    if users[uid]['password'] != hash_password(old_pw):
        return jsonify({'success': False, 'error': 'Ancien mot de passe incorrect'}), 403
    users[uid]['password'] = hash_password(new_pw)
    save_users(users)
    return jsonify({'success': True})

# ── SETTINGS ──

@app.route('/api/settings', methods=['GET'])
@require_auth
def get_settings():
    return jsonify({'success': True, 'settings': load_settings(current_user_id())})

@app.route('/api/settings', methods=['POST'])
@require_auth
def update_settings():
    data = request.json or {}
    settings = load_settings(current_user_id())
    settings.update(data)
    save_settings(settings, current_user_id())
    return jsonify({'success': True, 'settings': settings})

# ── ADMIN ──

@app.route('/api/admin/users', methods=['GET'])
@require_admin
def admin_list_users():
    users = load_users()
    safe = [{'id': u['id'], 'username': u['username'], 'role': u['role'],
             'created_at': u.get('created_at')} for u in users.values()]
    return jsonify({'success': True, 'users': safe})

@app.route('/api/admin/users', methods=['POST'])
@require_admin
def admin_create_user():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    role     = data.get('role', 'user')
    if not username or not password:
        return jsonify({'success': False, 'error': 'Username et password requis'}), 400
    if len(password) < 6:
        return jsonify({'success': False, 'error': 'Password min 6 chars'}), 400
    if role not in ('admin', 'user'):
        role = 'user'
    users = load_users()
    if any(u['username'] == username for u in users.values()):
        return jsonify({'success': False, 'error': 'Username déjà pris'}), 409
    uid = str(uuid.uuid4())
    users[uid] = {'id': uid, 'username': username, 'password': hash_password(password),
                  'role': role, 'created_at': time.time()}
    save_users(users)
    return jsonify({'success': True, 'id': uid, 'username': username, 'role': role})

@app.route('/api/admin/users/<user_id>', methods=['DELETE'])
@require_admin
def admin_delete_user(user_id):
    if user_id == current_user_data().get('user_id'):
        return jsonify({'success': False, 'error': 'Tu ne peux pas te supprimer toi-même'}), 400
    users = load_users()
    if user_id not in users:
        return jsonify({'success': False, 'error': 'Utilisateur introuvable'}), 404
    del users[user_id]
    save_users(users)
    return jsonify({'success': True})

@app.route('/api/admin/users/<user_id>/reset-password', methods=['POST'])
@require_admin
def admin_reset_password(user_id):
    data   = request.json or {}
    new_pw = data.get('password', '')
    if not new_pw or len(new_pw) < 6:
        return jsonify({'success': False, 'error': 'Password min 6 chars'}), 400
    users = load_users()
    if user_id not in users:
        return jsonify({'success': False, 'error': 'Utilisateur introuvable'}), 404
    users[user_id]['password'] = hash_password(new_pw)
    save_users(users)
    return jsonify({'success': True})

# ── STATS ──

@app.route('/api/stats', methods=['GET'])
@require_auth
def get_stats():
    stats    = load_stats(current_user_id())
    accounts = load_accounts(current_user_id())
    stats['accounts'] = len(accounts)
    return jsonify({'success': True, 'stats': stats})

@app.route('/api/stats/reset', methods=['POST'])
@require_auth
def reset_stats():
    save_stats({"swipes": 0, "messages": 0, "matches": 0, "replies": 0, "cta_sent": 0}, current_user_id())
    return jsonify({'success': True})

@app.route('/api/stats/history', methods=['GET'])
@require_auth
def get_stats_history():
    return jsonify({'success': True, 'history': load_stats_history(current_user_id())})

@app.route('/api/stats/alltime', methods=['GET'])
@require_auth
def get_stats_alltime():
    history = load_stats_history(current_user_id())
    total   = {'swipes': 0, 'messages': 0, 'matches': 0, 'replies': 0, 'cta_sent': 0}
    for e in history:
        for k in total: total[k] += e.get(k, 0)
    return jsonify({'success': True, 'alltime': total, 'days': len(history)})

# ── ACCOUNTS ──

@app.route('/api/accounts', methods=['GET'])
@require_auth
def get_accounts():
    accounts = load_accounts(current_user_id())
    safe = [{
        'user_id': a.get('user_id'),
        'name': a.get('name'),
        'has_refresh': bool(a.get('refresh_token')),
        'tinder_version': a.get('tinder_version', '17.3.0'),
        'bio': a.get('bio', ''),
        'photo': a.get('photo', ''),
        'age': a.get('age', ''),
        'tags': a.get('tags', []),
        'total_likes': a.get('total_likes'),
        'total_matches': a.get('total_matches'),
        'cached_match_count': a.get('cached_match_count'),
        'added_at': a.get('added_at', ''),
        '_alive': a.get('_alive'),
        # Proxy par compte
        'proxy_enabled': a.get('proxy_enabled', False),
        'proxy_url': a.get('proxy_url', ''),
    } for a in accounts]
    return jsonify({'success': True, 'accounts': safe})

@app.route('/api/accounts', methods=['POST'])
@require_auth
def add_account():
    data     = request.json
    required = ['token', 'persistent_device_id', 'device_id']
    if not all(k in data for k in required):
        return jsonify({'success': False, 'error': 'Champs requis: token, persistent_device_id, device_id'}), 400

    # Proxy du compte (optionnel à l'ajout)
    account_proxy_url     = data.get('proxy_url', '').strip()
    account_proxy_enabled = bool(data.get('proxy_enabled', False)) and bool(account_proxy_url)

    # On utilise le proxy du compte pour la vérification si disponible, sinon global
    if account_proxy_enabled and account_proxy_url:
        check_proxies = {'http': account_proxy_url, 'https': account_proxy_url}
    else:
        check_proxies = get_proxies(current_user_id())

    temp_account = {
        'token': data['token'],
        'persistent_device_id': data['persistent_device_id'],
        'device_id': data['device_id'],
        'user_id': 'temp_check',
        'ios_version': data.get('ios_version', '18,4,3'),
        'tinder_version': data.get('tinder_version', '17.3.0'),
        'app_version': data.get('app_version', '6630'),
        'latitude': data.get('latitude', 48.8566),
        'longitude': data.get('longitude', 2.3522),
    }

    result = tinder_check_token(temp_account, check_proxies)
    if not result['valid']:
        return jsonify({'success': False, 'error': result['error']}), 400

    account = {
        **temp_account,
        'user_id': result['user_id'],
        'name': result['name'],
        'bio': result.get('bio', ''),
        'photo': result.get('photo', ''),
        'age': result.get('age', ''),
        'tags': data.get('tags', []),
        'added_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        '_alive': True,
        # Proxy par compte
        'proxy_enabled': account_proxy_enabled,
        'proxy_url': account_proxy_url,
    }
    if data.get('refresh_token'):
        account['refresh_token'] = data['refresh_token']

    accounts = load_accounts(current_user_id())
    if any(a['user_id'] == account['user_id'] for a in accounts):
        return jsonify({'success': False, 'error': 'Compte déjà existant'}), 409

    accounts.append(account)
    save_accounts(accounts, current_user_id())
    return jsonify({'success': True, 'name': result['name'], 'user_id': result['user_id']})

@app.route('/api/accounts/<user_id>', methods=['DELETE'])
@require_auth
def delete_account(user_id):
    accounts       = load_accounts(current_user_id())
    original_count = len(accounts)
    accounts       = [a for a in accounts if a['user_id'] != user_id]
    if len(accounts) == original_count:
        return jsonify({'success': False, 'error': 'Compte introuvable'}), 404
    save_accounts(accounts, current_user_id())
    return jsonify({'success': True})

@app.route('/api/accounts/<user_id>/tags', methods=['POST'])
@require_auth
def update_account_tags(user_id):
    tags     = request.json.get('tags', [])
    accounts = load_accounts(current_user_id())
    for a in accounts:
        if a['user_id'] == user_id:
            a['tags'] = tags
    save_accounts(accounts, current_user_id())
    return jsonify({'success': True})

@app.route('/api/accounts/<user_id>/proxy', methods=['POST'])
@require_auth
def update_account_proxy(user_id):
    """Met à jour le proxy d'un compte spécifique."""
    data      = request.json or {}
    proxy_url = data.get('proxy_url', '').strip()
    enabled   = bool(data.get('proxy_enabled', False)) and bool(proxy_url)

    accounts = load_accounts(current_user_id())
    account  = next((a for a in accounts if a['user_id'] == user_id), None)
    if not account:
        return jsonify({'success': False, 'error': 'Compte introuvable'}), 404

    account['proxy_url']     = proxy_url
    account['proxy_enabled'] = enabled
    save_accounts(accounts, current_user_id())
    return jsonify({'success': True, 'proxy_enabled': enabled, 'proxy_url': proxy_url})


@app.route('/api/accounts/<user_id>/proxy/test', methods=['GET', 'POST'])
@require_auth
def test_account_proxy(user_id):
    """Teste le proxy d'un compte spécifique — ou un proxy passé en body."""
    accounts = load_accounts(current_user_id())
    account  = next((a for a in accounts if a['user_id'] == user_id), None)
    if not account:
        return jsonify({'success': False, 'error': 'Compte introuvable'}), 404

    # Si on passe un proxy_url dans le body, on teste celui-là directement
    data = request.json or {}
    test_url = data.get('proxy_url', '').strip()
    
    if test_url:
        proxies = {'http': test_url, 'https': test_url}
        using_account_proxy = True
    else:
        proxies = get_proxies_for_account(account, current_user_id())
        using_account_proxy = account.get('proxy_enabled', False) and bool(account.get('proxy_url'))
    
    ip = get_current_ip(proxies)
    return jsonify({'success': bool(ip), 'ip': ip,
                    'using_account_proxy': using_account_proxy})


@app.route('/api/accounts/<user_id>/bio', methods=['POST'])
@require_auth
def update_bio(user_id):
    bio      = request.json.get('bio', '')
    accounts = load_accounts(current_user_id())
    account  = next((a for a in accounts if a['user_id'] == user_id), None)
    if not account:
        return jsonify({'success': False, 'error': 'Compte introuvable'}), 404
    
    proxies = get_proxies_for_account(account, current_user_id())
    print(f"[BIO DEBUG] account keys={list(account.keys())}")
    print(f"[BIO DEBUG] user_id={account.get('user_id')}")
    print(f"[BIO DEBUG] token present={bool(account.get('token'))}")
    print(f"[BIO DEBUG] proxies={proxies}")
    
    result = tinder_update_bio(account, bio, proxies)
    print(f"[BIO DEBUG] result={result}")
    
    if result['success']:
        for a in accounts:
            if a['user_id'] == user_id:
                a['bio'] = bio
        save_accounts(accounts, current_user_id())
    return jsonify(result)

@app.route('/api/accounts/check', methods=['POST'])
@require_auth
def check_tokens():
    accounts    = load_accounts(current_user_id())
    results     = []
    settings    = load_settings(current_user_id())
    auto_delete = settings.get('auto_delete_dead', False)

    for account in accounts:
        # Chaque compte utilise son propre proxy pour la vérification
        proxies = get_proxies_for_account(account, current_user_id())
        r              = tinder_check_token(account, proxies)
        account['_alive'] = r['valid']
        results.append({'name': account['name'], 'user_id': account['user_id'], 'valid': r['valid']})
        if r['valid']:
            account['bio']   = r.get('bio',   account.get('bio', ''))
            account['photo'] = r.get('photo', account.get('photo', ''))
            account['age']   = r.get('age',   account.get('age', ''))

    if auto_delete:
        dead_count = sum(1 for a in accounts if not a.get('_alive', True))
        accounts   = [a for a in accounts if a.get('_alive', True)]
        print(f"🗑 Auto-delete: {dead_count} compte(s) supprimé(s)")

    save_accounts(accounts, current_user_id())
    return jsonify({'success': True, 'results': results})

@app.route('/api/accounts/match-counts', methods=['GET'])
@require_auth
def get_match_counts():
    user_id  = current_user_id()
    accs     = load_accounts(user_id)
    result   = {}
    for account in accs:
        try:
            proxies = get_proxies_for_account(account, user_id)
            tinder_init_session(account, proxies)
            matches_r = tinder_get_matches(account, 100, proxies)
            convs_r   = tinder_get_conversations(account, 100, proxies)
            all_ids   = set()
            if matches_r.get('success'):
                for m in matches_r['matches']:
                    mid = m.get('_id')
                    if mid: all_ids.add(mid)
            if convs_r.get('success'):
                for c in convs_r['conversations']:
                    mid = c.get('_id')
                    if mid: all_ids.add(mid)
            result[account['user_id']]      = len(all_ids)
            account['cached_match_count']   = len(all_ids)
        except Exception:
            result[account['user_id']] = account.get('cached_match_count', 0)
    save_accounts(accs, user_id)
    return jsonify({'success': True, 'counts': result})

# ── TAGS ──

@app.route('/api/tags', methods=['GET'])
@require_auth
def get_tags():
    return jsonify({'success': True, 'tags': load_tags(current_user_id())})

@app.route('/api/tags', methods=['POST'])
@require_auth
def create_tag():
    data  = request.json or {}
    name  = data.get('name', '').strip()
    color = data.get('color', '#448aff')
    if not name:
        return jsonify({'success': False, 'error': 'Nom requis'}), 400
    tags = load_tags(current_user_id())
    if any(t['name'].lower() == name.lower() for t in tags):
        return jsonify({'success': False, 'error': 'Tag déjà existant'}), 409
    tag = {'id': str(uuid.uuid4())[:8], 'name': name, 'color': color}
    tags.append(tag)
    save_tags(tags, current_user_id())
    return jsonify({'success': True, 'tag': tag})

@app.route('/api/tags/<tag_id>', methods=['PUT'])
@require_auth
def update_tag(tag_id):
    data = request.json or {}
    tags = load_tags(current_user_id())
    for t in tags:
        if t['id'] == tag_id:
            t['name']  = data.get('name',  t['name']).strip()
            t['color'] = data.get('color', t['color'])
    save_tags(tags, current_user_id())
    return jsonify({'success': True})

@app.route('/api/tags/<tag_id>', methods=['DELETE'])
@require_auth
def delete_tag(tag_id):
    tags = load_tags(current_user_id())
    tags = [t for t in tags if t['id'] != tag_id]
    save_tags(tags, current_user_id())
    accounts = load_accounts(current_user_id())
    for a in accounts:
        a['tags'] = [tid for tid in a.get('tags', []) if tid != tag_id]
    save_accounts(accounts, current_user_id())
    return jsonify({'success': True})

# ── AUTOMATION ──

@app.route('/api/automation', methods=['GET'])
@require_auth
def get_automation():
    tasks  = load_automation(current_user_id())
    result = []
    for t in tasks:
        tid  = t['id']
        live = automation_jobs.get(tid, {})
        result.append({**t, 'status': live.get('status', 'stopped'),
                       'next_run_str': live.get('next_run_str', '—'),
                       'log': live.get('log', [])[-30:]})
    return jsonify({'success': True, 'tasks': result})

@app.route('/api/automation', methods=['POST'])
@require_auth
def create_automation():
    data = request.json or {}
    task = {
        'id': str(uuid.uuid4())[:8],
        'name': data.get('name', 'Tâche auto'),
        'type': data.get('type', 'massdm'),
        'interval_minutes': int(data.get('interval_minutes', 30)),
        'account_ids': data.get('account_ids', []),
        'username': data.get('username', ''),
        'social_network': data.get('social_network', 'Instagram'),
        'swipe_count': int(data.get('swipe_count', 50)),
        'like_pct': int(data.get('like_pct', 80)),
        'parallel': bool(data.get('parallel', False)),
        'created_at': time.time(),
    }
    tasks = load_automation(current_user_id())
    tasks.append(task)
    save_automation(tasks, current_user_id())
    return jsonify({'success': True, 'task': task})

@app.route('/api/automation/<task_id>/start', methods=['POST'])
@require_auth
def start_automation(task_id):
    tasks = load_automation(current_user_id())
    task  = next((t for t in tasks if t['id'] == task_id), None)
    if not task:
        return jsonify({'success': False, 'error': 'Tâche introuvable'}), 404
    if automation_jobs.get(task_id, {}).get('status') == 'running':
        return jsonify({'success': False, 'error': 'Déjà en cours'}), 400
    automation_jobs[task_id] = {'status': 'running', 'log': [], 'next_run_str': '—'}
    t = threading.Thread(target=run_automation_task, args=(task_id, task, current_user_id()), daemon=True)
    t.start()
    automation_threads[task_id] = t
    return jsonify({'success': True})

@app.route('/api/automation/<task_id>/stop', methods=['POST'])
@require_auth
def stop_automation(task_id):
    if task_id in automation_jobs:
        automation_jobs[task_id]['status'] = 'stopped'
    return jsonify({'success': True})

@app.route('/api/automation/<task_id>', methods=['DELETE'])
@require_auth
def delete_automation(task_id):
    if task_id in automation_jobs:
        automation_jobs[task_id]['status'] = 'stopped'
    tasks = load_automation(current_user_id())
    tasks = [t for t in tasks if t['id'] != task_id]
    save_automation(tasks, current_user_id())
    return jsonify({'success': True})

@app.route('/api/automation/<task_id>/status', methods=['GET'])
@require_auth
def automation_status(task_id):
    live = automation_jobs.get(task_id, {})
    return jsonify({'success': True, 'status': live.get('status', 'stopped'),
                    'next_run_str': live.get('next_run_str', '—'),
                    'log': live.get('log', [])[-50:]})

# ── SWIPE ──

@app.route('/api/swipe/start', methods=['POST'])
@require_auth
def start_swipe():
    data        = request.json
    job_id      = str(uuid.uuid4())[:8]
    account_ids = data.get('account_ids', [])
    swipe_count = int(data.get('swipe_count', 50))
    like_pct    = int(data.get('like_percentage', 80))
    mode        = data.get('mode', 'basic')
    parallel    = bool(data.get('parallel', False))
    threading.Thread(target=run_auto_swipe,
        args=(job_id, account_ids, swipe_count, like_pct, mode, current_user_id(), parallel),
        daemon=True).start()
    return jsonify({'success': True, 'job_id': job_id})

@app.route('/api/swipe/status/<job_id>', methods=['GET'])
@require_auth
def swipe_status(job_id):
    if job_id not in swipe_progress:
        return jsonify({'success': False, 'error': 'Job introuvable'}), 404
    return jsonify({'success': True, **swipe_progress[job_id]})

# ── MASS DM ──

@app.route('/api/dm/start', methods=['POST'])
@require_auth
def start_dm():
    data           = request.json
    job_id         = str(uuid.uuid4())[:8]
    account_ids    = data.get('account_ids', [])
    username       = data.get('username', '')
    social_network = data.get('social_network', 'Instagram')
    mode           = data.get('mode', 'massdm')
    if not username:
        return jsonify({'success': False, 'error': 'Username requis'}), 400
    threading.Thread(target=run_mass_dm,
        args=(job_id, account_ids, username, social_network, mode, current_user_id()),
        daemon=True).start()
    return jsonify({'success': True, 'job_id': job_id})

@app.route('/api/dm/status/<job_id>', methods=['GET'])
@require_auth
def dm_status(job_id):
    if job_id not in dm_progress:
        return jsonify({'success': False, 'error': 'Job introuvable'}), 404
    return jsonify({'success': True, **dm_progress[job_id]})

# ── PROXY GLOBAL ──

@app.route('/api/proxy', methods=['GET'])
@require_auth
def get_proxy():
    return jsonify({'success': True, 'proxy': load_proxy(current_user_id())})

@app.route('/api/proxy', methods=['POST'])
@require_auth
def set_proxy():
    data   = request.json
    config = {'enabled': data.get('enabled', False),
              'proxy_url': data.get('proxy_url'),
              'rotation_link': data.get('rotation_link')}
    save_proxy(config, current_user_id())
    return jsonify({'success': True})

@app.route('/api/proxy/test', methods=['GET'])
@require_auth
def test_proxy():
    proxies = get_proxies(current_user_id())
    ip      = get_current_ip(proxies)
    return jsonify({'success': bool(ip), 'ip': ip})

@app.route('/api/proxy/rotate', methods=['POST'])
@require_auth
def rotate_proxy():
    cfg = load_proxy(current_user_id())
    if not cfg['enabled'] or not cfg['rotation_link']:
        return jsonify({'success': False, 'error': 'Rotation non configurée'}), 400
    try:
        requests.get(cfg['rotation_link'], timeout=10, verify=False)
        time.sleep(3)
        proxies = get_proxies(current_user_id())
        ip      = get_current_ip(proxies)
        return jsonify({'success': True, 'new_ip': ip})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ── MATCHES ──

@app.route('/api/matches', methods=['GET'])
@require_auth
def get_matches_list():
    accounts    = load_accounts(current_user_id())
    all_matches = []
    for account in accounts:
        proxies = get_proxies_for_account(account, current_user_id())
        r = tinder_get_matches(account, 30, proxies)
        if r['success']:
            for m in r['matches']:
                all_matches.append({
                    'account': account['name'],
                    'match_id': m.get('_id'),
                    'name': m.get('person', {}).get('name', 'N/A'),
                    'photo': (m.get('person', {}).get('photos') or [{}])[0].get('url', ''),
                    'last_message': (m.get('messages') or [{}])[-1].get('message', '') if m.get('messages') else '',
                })
    return jsonify({'success': True, 'matches': all_matches})

# ============================================================
# RESET AUTO MINUIT
# ============================================================

def check_and_reset_stats():
    import datetime
    today = datetime.date.today().isoformat()
    try:
        with open(STATS_FILE, 'r') as f:
            all_data = json.load(f)
    except:
        all_data = {}

    changed = False
    users   = load_users()
    for uid in list(users.keys()) + ['default']:
        data       = all_data.get(uid, {})
        last_reset = data.get('last_reset', None)
        if last_reset != today:
            all_data[uid] = {'swipes': 0, 'messages': 0, 'matches': 0,
                             'replies': 0, 'cta_sent': 0, 'last_reset': today}
            changed = True

    if changed:
        print(f"🔄 Nouveau jour ({today}) — reset stats")
        with open(STATS_FILE, 'w') as f:
            json.dump(all_data, f, indent=2)
    else:
        print(f"✅ Stats du jour déjà chargées ({today})")



from flask import send_from_directory

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_frontend(path):
    return send_from_directory('templates', 'index.html')



# ============================================================
# LANCEMENT
# ============================================================

ensure_admin_exists()
check_and_reset_stats()

if __name__ == '__main__':
    print("🚀 Backend panel démarré sur http://localhost:5002")
    app.run(host='0.0.0.0', port=8080, debug=False)
