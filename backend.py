"""
Backend Flask - API REST pour le panel web Tinder Bot
Basé sur le bot Telegram existant - réutilise TinderAPI et FruitzAPI
"""
from flask import render_template
from flask import Flask, request, jsonify, session
from flask_cors import CORS
app = Flask(__name__)
CORS(app)

@app.route("/")
def home():
    return render_template("index.html")
import json
import time
import random
import threading
import uuid
import os
import hashlib
import secrets

# ============================================================
# IMPORTS DU BOT (copie des classes depuis ton bot.py)
# ============================================================
try:
    from curl_cffi import requests as curl_requests
    CURL_CFFI_AVAILABLE = True
except ImportError:
    import requests as curl_requests
    CURL_CFFI_AVAILABLE = False

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# IA
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

# Stockage des tokens actifs en mémoire: {token: {user_id, username, role}}
active_tokens = {}

def generate_token():
    return secrets.token_hex(32)

def get_token_from_request():
    return request.headers.get('X-Auth-Token', '') or ''

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

# ============================================================
# HELPERS (identiques au bot)
# ============================================================

def generate_device_id_from_user_id(user_id):
    import hashlib
    hash_obj = hashlib.md5(f"fruitz_{user_id}".encode())
    return hash_obj.hexdigest().upper()

def generate_session_id():
    return str(uuid.uuid4())

def generate_request_id():
    return str(uuid.uuid4())

def generate_sentry_trace():
    trace_id = uuid.uuid4().hex
    span_id = uuid.uuid4().hex[:16]
    return f"{trace_id}-{span_id}"

def generate_baggage(trace_id):
    return (
        "sentry-environment=production,"
        "sentry-public_key=5fafb8140a654df29aa396de5b7261d4,"
        f"sentry-trace_id={trace_id},"
        "sentry-sample_rate=0.05,"
        "sentry-transaction=Route%20Change,"
        "sentry-sampled=false"
    )

def get_current_ip(proxies=None):
    try:
        resp = requests.get('https://api.ipify.org?format=json', proxies=proxies, timeout=10, verify=False)
        return resp.json()['ip']
    except:
        return None

# ============================================================
# FICHIERS DE DONNÉES
# ============================================================

ACCOUNTS_FILE    = "tinder_accounts.json"
PROXIES_FILE     = "user_proxies.json"
HISTORY_FILE     = "message_history.json"
STATS_FILE       = "tinder_stats.json"
STATS_HISTORY_FILE = "tinder_stats_history.json"
USERS_FILE       = "panel_users.json"
TAGS_FILE        = "panel_tags.json"
AUTOMATION_FILE  = "automation_config.json"

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

def load_stats_history(user_id="default"):
    """Retourne la liste des entrées historiques: [{date, swipes, messages, matches}]"""
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
    """Ajoute une entrée dans l'historique pour aujourd'hui."""
    import datetime
    today = datetime.date.today().isoformat()
    stats = load_stats(user_id)
    history = load_stats_history(user_id)
    # Mettre à jour ou ajouter l'entrée du jour
    existing = next((e for e in history if e['date'] == today), None)
    if existing:
        existing['swipes']   = stats.get('swipes', 0)
        existing['messages'] = stats.get('messages', 0)
        existing['matches']  = stats.get('matches', 0)
    else:
        history.append({'date': today, 'swipes': stats.get('swipes', 0),
                        'messages': stats.get('messages', 0), 'matches': stats.get('matches', 0)})
    save_stats_history(history, user_id)

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

# ============================================================
# AUTH HELPERS
# ============================================================

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
    """Crée un admin par défaut si aucun utilisateur n'existe."""
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
        print("⚠️  Change le mot de passe admin immédiatement !")


def save_stats(stats, user_id="default"):
    import datetime
    try:
        with open(STATS_FILE, 'r') as f:
            all_data = json.load(f)
    except:
        all_data = {}
    # Préserver last_reset pour éviter le reset au redémarrage
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
# TINDER API (extrait du bot)
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

def make_request(method, url, headers, proxies=None, json_data=None, data=None, timeout=10):
    if CURL_CFFI_AVAILABLE:
        try:
            if method == 'GET':
                return curl_requests.get(url, headers=headers, proxies=proxies, timeout=timeout, impersonate="safari15_5", verify=False)
            elif method == 'POST':
                return curl_requests.post(url, headers=headers, json=json_data, data=data, proxies=proxies, timeout=timeout, impersonate="safari15_5", verify=False)
        except:
            pass
    if method == 'GET':
        return requests.get(url, headers=headers, proxies=proxies, timeout=timeout, verify=False)
    elif method == 'POST':
        return requests.post(url, headers=headers, json=json_data, data=data, proxies=proxies, timeout=timeout, verify=False)

def generate_content_hash():
    import hashlib, base64, string
    random_str = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    hash_bytes = hashlib.sha256(random_str.encode()).digest()
    return base64.b64encode(hash_bytes).decode('utf-8').rstrip('=')

# --- TINDER API CALLS ---

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
        resp = make_request('POST', f"https://api.gotinder.com/user/matches/{match_id}", headers, proxies=proxies, json_data={"message": message_text})
        if resp.status_code == 200:
            return {'success': True}
        return {'success': False, 'error': f"HTTP {resp.status_code}", 'details': resp.text[:200]}
    except Exception as e:
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
        resp = make_request('POST', 'https://api.gotinder.com/v2/profile/user', headers, proxies=proxies, json_data={"bio": bio})
        return {'success': resp.status_code == 200, 'error': f"HTTP {resp.status_code}" if resp.status_code != 200 else None}
    except Exception as e:
        return {'success': False, 'error': str(e)}

# ============================================================
# IA (Groq)
# ============================================================

def generate_ai_reply(conversation_history, match_name, match_bio, username, social_network):
    if not GROQ_AVAILABLE and not GROQ_API_KEY:
        return None

    our_messages   = [m for m in conversation_history if m['sender'] == 'NOUS']
    their_messages = [m for m in conversation_history if m['sender'] != 'NOUS']
    formatted = "\n".join([f"{m['sender']}: {m['text']}" for m in conversation_history[-10:]])

    # ═══════════════════════════════════════════════════════════
    # PHASE 1 : DÉTECTION DE L'ÉTAT DE LA CONVERSATION
    # ═══════════════════════════════════════════════════════════

    # A. Vérifier si redirection déjà effectuée
    already_redirected = False
    if username:
        redirect_markers = [username.lower(), 'insta', 'instagram', social_network.lower() if social_network else '']
        for msg in our_messages:
            msg_lower = msg['text'].lower()
            if any(marker in msg_lower for marker in redirect_markers if marker):
                already_redirected = True
                break

    # B. Détecter si il propose un réseau social
    he_proposes_social = False
    he_proposes_insta  = False
    he_proposes_snap   = False

    if their_messages:
        last_msg = their_messages[-1]['text'].lower()
        if 'insta' in last_msg or 'instagram' in last_msg:
            he_proposes_insta = True
            he_proposes_social = True
        elif 'snap' in last_msg or 'snapchat' in last_msg:
            he_proposes_snap = True
            he_proposes_social = True
        elif any(w in last_msg for w in ['whatsapp', 'telegram', 'numero', 'numéro', 'appel']):
            he_proposes_social = True

    # C. Détecter demande de localisation
    location_keywords = ["d'où", "d ou", 'où', 'ville', 'habite', 'vis', 'viens', 'secteur', 'coin', 'region']
    he_asked_location = any(any(kw in msg['text'].lower() for kw in location_keywords) for msg in their_messages)
    we_asked_location = any(any(kw in msg['text'].lower() for kw in location_keywords) for msg in our_messages)

    # D. Extraire sa ville si mentionnée
    his_city = None
    cities = ['paris', 'marseille', 'lyon', 'toulouse', 'nice', 'nantes',
              'strasbourg', 'montpellier', 'bordeaux', 'lille', 'rennes',
              'aix', 'cannes', 'antibes', 'toulon']
    for msg in their_messages:
        for city in cities:
            if city in msg['text'].lower():
                his_city = city
                break
        if his_city:
            break

    # E. Décision redirection automatique
    should_redirect = False
    total_exchanges = min(len(our_messages), len(their_messages))
    if not already_redirected and username and social_network and total_exchanges >= 4:
        probability = 0.95 if total_exchanges >= 7 else 0.85
        should_redirect = random.random() < probability

    # ═══════════════════════════════════════════════════════════
    # PHASE 2 : CONSTRUCTION DU PROMPT SELON LE CONTEXTE
    # ═══════════════════════════════════════════════════════════

    # CAS 1 : Il propose un réseau social (PRIORITÉ ABSOLUE)
    if he_proposes_social and not already_redirected:
        if he_proposes_insta:
            prompt = f"""Tu es une fille de 20 ans sur Tinder. {match_name} propose Instagram.

Historique:
{formatted}

Mission : Accepte avec joie et donne ton Instagram ({username}).

Exemples (choisis-en un) :
- "Ouiii carrément ! C'est {username} 🥰"
- "Yes ! C'est {username} ☺️"
- "Grave ! Cherche {username} 😊"

Règles : 10-15 mots max, commence par majuscule, 1 emoji max, ton enjoué, pas de guillemets."""

        elif he_proposes_snap:
            prompt = f"""Tu es une fille de 20 ans sur Tinder. {match_name} propose Snapchat.

Historique:
{formatted}

Mission : Refuse Snap poliment et donne Instagram ({username}).

Exemples (choisis-en un) :
- "Ah désolée j'ai pas snap 😅 par contre {username} sur insta !"
- "Non j'utilise que insta moi, c'est {username} 🙈"

Règles : 15-20 mots max, commence par majuscule, 1 emoji max, refuse Snap, donne Instagram, pas de guillemets."""

        else:
            prompt = f"""Tu es une fille de 20 ans sur Tinder. {match_name} propose un autre réseau.

Historique:
{formatted}

Mission : Redirige vers Instagram ({username}).

Exemple : "J'ai que insta moi, c'est {username} 🙈"

Règles : 15 mots max, commence par majuscule, 1 emoji max, pas de guillemets."""

    # CAS 2 : Redirection automatique (après 4+ échanges)
    elif should_redirect:
        prompt = f"""Tu es une fille de 20 ans sur Tinder avec {match_name}.

Historique:
{formatted}

Mission : Continue la conversation ET mentionne ton {social_network}.

Structure :
1. Réponds à son dernier message (10 mots max)
2. Ajoute UNE excuse pour aller sur {social_network}

Excuses possibles (choisis-en UNE) :
- "C'est relou d'écrire ici, je peux pas faire de vocaux ptdr. {username} sur {social_network} ?"
- "Je réponds jamais ici mdr, je suis plus sur {social_network}. C'est {username} 😅"
- "Cette appli bug chez moi... {username} sur {social_network} plutôt ? 🙈"

Règles : 25-35 mots total, commence par majuscule, ton naturel, 1-2 emojis max, pas de guillemets."""

    # CAS 3 : Après redirection (négociation)
    elif already_redirected:
        last_msg = their_messages[-1]['text'].lower() if their_messages else ""

        if any(w in last_msg for w in ['ok', 'ouais', 'oui', 'dac', 'go', 'cool', 'parfait', "c'est fait", 'fait']):
            prompt = f"""Tu es une fille de 20 ans. {match_name} accepte d'aller sur Instagram.

Historique:
{formatted}

Mission : Confirme avec joie. NE répète PAS ton username.

Exemples (choisis-en un) :
- "Trop bien ! J'attends ton message 🥰"
- "Cool ! À tout de suite là-bas 😊"
- "Parfait mdr ! Je check souvent 🙈"

Règles : 8-12 mots max, commence par majuscule, 1 emoji max, NE répète PAS le username, pas de guillemets."""

        elif any(w in last_msg for w in ['non', 'pas', 'reste', 'ici', 'tinder', 'flemme']):
            prompt = f"""Tu es une fille de 20 ans. {match_name} refuse d'aller sur Instagram.

Historique:
{formatted}

Mission : Insiste avec UNE excuse convaincante et rappelle {username}.

Excuses (choisis-en UNE) :
- "Mais j'ai jamais les notifs ici... {username} sur insta je réponds direct 🙈"
- "Tinder bug tout le temps chez moi... {username} sur insta c'est mieux ☺️"
- "De toute façon je supprime l'appli bientôt... {username} sur insta avant 😅"

Règles : 15-20 mots max, commence par majuscule, 1 emoji max, insiste, rappelle username, pas de guillemets."""

        elif any(w in last_msg for w in ['insta', 'snap', "c'est quoi", 'c quoi', 'ton insta']):
            prompt = f"""Tu es une fille de 20 ans. {match_name} redemande ton contact.

Historique:
{formatted}

Mission : Rappelle ton Instagram avec excuse.

Exemples (choisis-en un) :
- "{username.capitalize()} ptdr, je te l'ai dit ! J'ai pas les notifs ici 😅"
- "C'est {username} mdr, cette appli marche mal chez moi 🙈"

Règles : 15 mots max, commence par majuscule, 1 emoji max, rappelle username, pas de guillemets."""

        elif 'snap' in last_msg:
            prompt = f"""Tu es une fille de 20 ans. {match_name} insiste pour Snap.

Historique:
{formatted}

Mission : Refuse Snap, insiste pour Instagram {username}.

Exemple : "J'ai vraiment pas snap désolée 😅 par contre {username} sur insta !"

Règles : 15 mots max, commence par majuscule, 1 emoji max, refuse Snap, donne Instagram, pas de guillemets."""

        else:
            prompt = f"""Tu es une fille de 20 ans. Tu as donné ton Instagram ({username}) mais {match_name} continue sur Tinder.

Historique:
{formatted}

Mission : Réponds TRÈS BRIÈVEMENT (3-5 mots) puis ramène vers Instagram.

Exemples (choisis-en un) :
- "Lol ouais... mais sérieux {username} sur insta, j'ai pas les notifs ici 😅"
- "Ah cool ! {username} sur insta plutôt, cette appli bug chez moi 🙈"
- "Mdr ! Bon {username} sur insta, je réponds plus vite là-bas ☺️"

Règles : 15-20 mots total, commence par majuscule, 1 emoji max, réponds COURT puis ramène Insta, pas de guillemets."""

    # CAS 4 : Gestion de la localisation
    elif he_asked_location and not we_asked_location:
        if his_city:
            prompt = f"""Tu es une fille de 20 ans. {match_name} habite à {his_city}.

Historique:
{formatted}

Mission : Dis que tu habites là-bas aussi.

Exemples (choisis-en un) :
- "Oui moi aussi ! 😊"
- "Ah cool pareil mdr ! 🥰"
- "Genre on est voisins ptdr ! 🙈"

Règles : 8-12 mots max, commence par majuscule, 1 emoji max, confirme même ville, pas de guillemets."""

        else:
            prompt = f"""Tu es une fille de 20 ans. {match_name} demande où tu habites.

Historique:
{formatted}

Mission : Retourne la question AVANT de répondre.

Exemples (choisis-en un) :
- "Et toi t'es d'où du coup ? 😊"
- "Toi t'habites où ? 🙈"
- "Et toi t'es de quel coin ? ☺️"

Règles : 8-12 mots max, commence par majuscule, 1 emoji max, retourne la question, pas de guillemets."""

    # CAS 5 : Conversation normale
    else:
        questions_pool = [
            "Et toi tu fais quoi de beau ? 🥰",
            "T'as d'autres passions ? 🙈",
            "Qu'est-ce que tu aimes faire ? ☺️",
            "T'as des projets en ce moment ? 😊",
            "Tu fais quoi pour t'amuser ? 🥰",
            "T'es plutôt sortie ou tranquille chez toi ? 🙈",
            "Tu kiff quoi dans la vie ? ☺️",
            "T'as des hobbies ? 😊",
            "Tu fais quoi ce week-end ? 🥰"
        ]
        selected_questions = random.sample(questions_pool, 3)
        questions_text = "\n".join([f'- "{q}"' for q in selected_questions])

        prompt = f"""Tu es une fille de 20 ans mignonne sur Tinder avec {match_name}.

Bio de {match_name} : {match_bio if match_bio else "Pas de bio"}

Historique:
{formatted}

Mission : Réponds naturellement comme une vraie fille de 20 ans.

Ton style :
- Mignonne, un peu timide
- Utilise "lol", "mdr", "genre", "franchement"
- Emojis : 🥰 😊 🙈 ☺️ 😅 💕
- Pose des questions sur ses passions/activités/vie
- 10-20 mots max

Questions possibles (choisis UNE parmi celles-ci UNIQUEMENT) :
{questions_text}

RÈGLES CRITIQUES :
- Commence TOUJOURS par une MAJUSCULE
- 1 seul emoji à la fin max
- NE demande JAMAIS d'où il est (sauf s'il demande en premier)
- Choisis UNE question parmi celles proposées ci-dessus
- 10-20 mots max
- Pas de guillemets

Réponds UNIQUEMENT avec le message final."""

    # ═══════════════════════════════════════════════════════════
    # PHASE 3 : APPEL GROQ ET NETTOYAGE
    # ═══════════════════════════════════════════════════════════
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.9, "max_tokens": 150},
            timeout=30
        )
        if resp.status_code == 200:
            return resp.json()['choices'][0]['message']['content'].strip().strip('"').strip("'")
    except:
        pass
    return None

# ============================================================
# AUTOMATION SCHEDULER
# ============================================================

automation_jobs = {}   # task_id -> {status, next_run, log, ...}
automation_threads = {}  # task_id -> thread

def run_automation_task(task_id, task, user_id):
    """Tourne en boucle et exécute la tâche selon l'intervalle."""
    import datetime
    automation_jobs[task_id]['status'] = 'running'
    automation_jobs[task_id]['log'] = []

    def log(msg):
        automation_jobs[task_id]['log'].append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")
        if len(automation_jobs[task_id]['log']) > 500:
            automation_jobs[task_id]['log'] = automation_jobs[task_id]['log'][-500:]
        print(f"[AUTO:{task_id}] {msg}")

    interval_sec = int(task.get('interval_minutes', 30)) * 60
    task_type = task.get('type', 'massdm')
    parallel = task.get('parallel', False)

    log(f"⚡ Tâche démarrée — {task_type} toutes les {task.get('interval_minutes')}min — tous les comptes")

    while automation_jobs.get(task_id, {}).get('status') == 'running':
        next_run = time.time() + interval_sec
        automation_jobs[task_id]['next_run'] = next_run
        automation_jobs[task_id]['next_run_str'] = datetime.datetime.fromtimestamp(next_run).strftime('%H:%M:%S')

        log(f"🔁 Exécution cycle — {task_type}")

        try:
            job_id = str(uuid.uuid4())[:8]
            # Toujours utiliser tous les comptes — account_ids vide = tous
            account_ids = []

            if task_type in ('massdm', 'chatting'):
                username       = task.get('username', '')
                social_network = task.get('social_network', 'Instagram')
                mode           = task_type

                # Lancer dans le même thread pour capturer les logs en live
                # On redirige les logs du job vers les logs automation
                orig_log = dm_progress.get(job_id)
                t = threading.Thread(
                    target=run_mass_dm,
                    args=(job_id, account_ids, username, social_network, mode, user_id),
                    daemon=True
                )
                t.start()
                # Suivre les logs en temps réel
                while t.is_alive():
                    if automation_jobs.get(task_id, {}).get('status') != 'running':
                        break
                    job_logs = dm_progress.get(job_id, {}).get('log', [])
                    current_count = len(automation_jobs[task_id]['log'])
                    # Synchroniser les logs du job dans les logs automation
                    already_synced = automation_jobs[task_id].get('_dm_synced', 0)
                    for entry in job_logs[already_synced:]:
                        automation_jobs[task_id]['log'].append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}]   {entry}")
                    automation_jobs[task_id]['_dm_synced'] = len(job_logs)
                    time.sleep(1)
                t.join()
                # Sync logs finaux
                job_logs = dm_progress.get(job_id, {}).get('log', [])
                already_synced = automation_jobs[task_id].get('_dm_synced', 0)
                for entry in job_logs[already_synced:]:
                    automation_jobs[task_id]['log'].append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}]   {entry}")
                automation_jobs[task_id]['_dm_synced'] = 0

                sent = dm_progress.get(job_id, {}).get('total_sent', 0)
                skipped = dm_progress.get(job_id, {}).get('total_skipped', 0)
                log(f"✅ Cycle terminé — {sent} envoyés, {skipped} ignorés")

            elif task_type in ('swipe', 'forcematch'):
                swipe_count = int(task.get('swipe_count', 50))
                like_pct    = int(task.get('like_pct', 80))
                mode        = 'forcematch' if task_type == 'forcematch' else 'basic'

                t = threading.Thread(
                    target=run_auto_swipe,
                    args=(job_id, account_ids, swipe_count, like_pct, mode, user_id, parallel),
                    daemon=True
                )
                t.start()
                while t.is_alive():
                    if automation_jobs.get(task_id, {}).get('status') != 'running':
                        break
                    job_logs = swipe_progress.get(job_id, {}).get('log', [])
                    already_synced = automation_jobs[task_id].get('_sw_synced', 0)
                    for entry in job_logs[already_synced:]:
                        automation_jobs[task_id]['log'].append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}]   {entry}")
                    automation_jobs[task_id]['_sw_synced'] = len(job_logs)
                    time.sleep(1)
                t.join()
                job_logs = swipe_progress.get(job_id, {}).get('log', [])
                already_synced = automation_jobs[task_id].get('_sw_synced', 0)
                for entry in job_logs[already_synced:]:
                    automation_jobs[task_id]['log'].append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}]   {entry}")
                automation_jobs[task_id]['_sw_synced'] = 0

                likes = swipe_progress.get(job_id, {}).get('total_likes', 0)
                matches = swipe_progress.get(job_id, {}).get('total_matches', 0)
                log(f"✅ Cycle terminé — {likes} likes, {matches} matchs")

            record_daily_stats(user_id)
        except Exception as e:
            log(f"❌ Erreur: {str(e)}")

        log(f"⏳ Prochain cycle dans {task.get('interval_minutes')}min")
        elapsed = 0
        while elapsed < interval_sec:
            if automation_jobs.get(task_id, {}).get('status') != 'running':
                break
            time.sleep(5)
            elapsed += 5

    automation_jobs[task_id]['status'] = 'stopped'
    log("🛑 Tâche arrêtée")

# Match count cache per account
match_count_cache = {}  # user_id -> {account_user_id: count}



swipe_progress = {}  # job_id -> dict

def run_auto_swipe(job_id, account_ids, swipe_count, like_pct, mode, user_id, parallel=False):
    accounts = load_accounts(user_id)
    accounts = [a for a in accounts if a['user_id'] in account_ids] if account_ids else accounts
    proxies = get_proxies(user_id)
    
    swipe_progress[job_id] = {
        'status': 'running',
        'total_accounts': len(accounts),
        'completed_accounts': 0,
        'total_likes': 0,
        'total_dislikes': 0,
        'total_matches': 0,
        'total_failed': 0,
        'accounts': [],
        'log': [],
        'parallel': parallel,
    }

    lock = threading.Lock()

    def log(msg):
        with lock:
            swipe_progress[job_id]['log'].append(msg)
        print(f"[{job_id}] {msg}")

    def process_account(account):
        log(f"▶ Démarrage {account['name']}...")
        tinder_init_session(account, proxies)
        time.sleep(random.uniform(1, 2))
        wly = tinder_get_fast_match_count(account, proxies).get('count', 0)

        if mode == 'forcematch':
            likes = dislikes = matches = failed = 0
            for cycle in range(1, swipe_count + 1):
                discover = tinder_get_profiles(account, 2, proxies)
                if not discover['success'] or len(discover['profiles']) < 2:
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
            likes = dislikes = matches = failed = 0
            if discover['success']:
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
            else:
                failed = swipe_count

        acc_result = {'name': account['name'], 'wly': wly, 'likes': likes, 'dislikes': dislikes, 'matches': matches, 'failed': failed}
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

    # Sauvegarder les stats persistantes globales
    stats = load_stats(user_id)
    stats['swipes']  += swipe_progress[job_id]['total_likes'] + swipe_progress[job_id]['total_dislikes']
    stats['matches'] += swipe_progress[job_id]['total_matches']
    save_stats(stats, user_id)
    record_daily_stats(user_id)

    # Persister les stats cumulées par compte sur l'objet account
    all_accounts = load_accounts(user_id)
    for acc_result in swipe_progress[job_id]['accounts']:
        for a in all_accounts:
            if a['name'] == acc_result['name']:
                a['total_likes']   = a.get('total_likes', 0)   + acc_result.get('likes', 0)
                a['total_matches'] = a.get('total_matches', 0) + acc_result.get('matches', 0)
                break
    save_accounts(all_accounts, user_id)

    swipe_progress[job_id]['status'] = 'done'

# ============================================================
# MASS DM WORKER (thread)
# ============================================================

dm_progress = {}

def run_mass_dm(job_id, account_ids, username, social_network, mode, user_id):
    accounts = load_accounts(user_id)
    accounts = [a for a in accounts if a['user_id'] in account_ids] if account_ids else accounts
    proxies = get_proxies(user_id)

    dm_progress[job_id] = {
        'status': 'running',
        'total_accounts': len(accounts),
        'completed_accounts': 0,
        'total_sent': 0,
        'total_skipped': 0,
        'total_failed': 0,
        'accounts': [],
        'log': []
    }

    fallback_messages = [
        f"Coucou, ça va ?",
        f"Hey ! Comment tu vas ?",
        f"Salut 😊",
        f"Cc ! Tu vas bien ?",
    ]

    def log(msg):
        dm_progress[job_id]['log'].append(msg)
        print(f"[DM:{job_id}] {msg}")

    for account in accounts:
        log(f"▶ Compte : {account['name']}")
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

        sent = skipped = failed = 0

        for match in all_matches:
            match_id   = match.get('_id')
            match_name = match.get('person', {}).get('name', 'Inconnu')
            match_bio  = match.get('person', {}).get('bio', '')

            if not match_id:
                failed += 1
                continue

            # Récupérer l'historique
            hist_r    = tinder_get_messages(account, match_id, proxies)
            messages  = hist_r.get('messages', [])

            # Analyser la convo
            last_sender = None
            has_their_reply = False
            conversation_history = []

            for msg in messages:
                sender_id = msg.get('from', '')
                text = msg.get('message', '')
                if sender_id == account['user_id']:
                    sender_label = 'NOUS'
                    last_sender = 'NOUS'
                else:
                    sender_label = match_name
                    last_sender = match_name
                    has_their_reply = True
                conversation_history.append({'sender': sender_label, 'text': text})

            # Logger toute la conversation
            log(f"  ─── 💬 {match_name} ({len(conversation_history)} msg) ───")
            if conversation_history:
                for m in conversation_history:
                    prefix = "  → NOUS" if m['sender'] == 'NOUS' else f"  ← {match_name}"
                    log(f"  {prefix}: {m['text'][:80]}")
            else:
                log(f"  (aucun message — nouveau match)")

            # Logique décision
            if last_sender == 'NOUS':
                skipped += 1
                log(f"  ⏭ {match_name} — en attente de réponse, on skip")
                continue

            if has_message_sent(user_id, account['user_id'], match_id) and not has_their_reply:
                skipped += 1
                log(f"  ⏭ {match_name} — déjà contacté, pas de réponse")
                continue

            # Générer le message
            if mode == 'chatting' and conversation_history:
                log(f"  🤖 Génération IA en cours...")
                msg_text = generate_ai_reply(conversation_history, match_name, match_bio, username, social_network)
                if msg_text:
                    log(f"  🤖 IA → \"{msg_text}\"")
                else:
                    msg_text = random.choice(fallback_messages)
                    log(f"  🤖 Fallback → \"{msg_text}\"")
            elif mode == 'massdm':
                msg_text = random.choice([
                    f"Coucou, ton profil m'a fait sourire haha ! Je suis plus sur {social_network}, cherche {username} si tu veux qu'on parle 😊",
                    f"Salut ! J'utilise plus trop cette appli... Je suis {username} sur {social_network} 🙈",
                    f"Hey ! Par contre je réponds pas souvent ici, {username} sur {social_network} c'est mieux !",
                ])
            else:
                msg_text = random.choice(fallback_messages)

            result = tinder_send_message(account, match_id, msg_text, proxies)
            if result['success']:
                sent += 1
                mark_message_sent(user_id, account['user_id'], match_id)
                log(f"  ✅ Envoyé à {match_name}")
            else:
                failed += 1
                log(f"  ❌ {match_name} — {result.get('error')}")

            time.sleep(random.uniform(2, 5))

        acc_result = {'name': account['name'], 'sent': sent, 'skipped': skipped, 'failed': failed}
        dm_progress[job_id]['accounts'].append(acc_result)
        dm_progress[job_id]['total_sent']    += sent
        dm_progress[job_id]['total_skipped'] += skipped
        dm_progress[job_id]['total_failed']  += failed
        dm_progress[job_id]['completed_accounts'] += 1

    # Sauvegarder les stats persistantes
    stats = load_stats(user_id)
    stats['messages'] += dm_progress[job_id]['total_sent']
    save_stats(stats, user_id)
    record_daily_stats(user_id)

    dm_progress[job_id]['status'] = 'done'

# ============================================================
# ROUTES API REST
# ============================================================

# ── AUTH ────────────────────────────────────────────────────

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    users = load_users()
    for uid, u in users.items():
        if u['username'] == username and u['password'] == hash_password(password):
            token = generate_token()
            active_tokens[token] = {'user_id': uid, 'username': u['username'], 'role': u['role']}
            return jsonify({'success': True, 'token': token, 'username': u['username'], 'role': u['role']})
    return jsonify({'success': False, 'error': 'Identifiants incorrects'}), 401



@app.route('/api/auth/logout', methods=['POST'])
def logout():
    token = get_token_from_request()
    if token in active_tokens:
        del active_tokens[token]
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
    data = request.json or {}
    old_pw = data.get('old_password', '')
    new_pw = data.get('new_password', '')
    if not new_pw or len(new_pw) < 6:
        return jsonify({'success': False, 'error': 'Mot de passe trop court (min 6 chars)'}), 400
    uid = current_user_data().get('user_id')
    users = load_users()
    if users[uid]['password'] != hash_password(old_pw):
        return jsonify({'success': False, 'error': 'Ancien mot de passe incorrect'}), 403
    users[uid]['password'] = hash_password(new_pw)
    save_users(users)
    return jsonify({'success': True})

# ── ADMIN — USER MANAGEMENT ─────────────────────────────────

@app.route('/api/admin/users', methods=['GET'])
@require_admin
def admin_list_users():
    users = load_users()
    safe = [{
        'id': u['id'],
        'username': u['username'],
        'role': u['role'],
        'created_at': u.get('created_at'),
    } for u in users.values()]
    return jsonify({'success': True, 'users': safe})

@app.route('/api/admin/users', methods=['POST'])
@require_admin
def admin_create_user():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')
    role = data.get('role', 'user')
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
    users[uid] = {
        'id': uid,
        'username': username,
        'password': hash_password(password),
        'role': role,
        'created_at': time.time(),
    }
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
    data = request.json or {}
    new_pw = data.get('password', '')
    if not new_pw or len(new_pw) < 6:
        return jsonify({'success': False, 'error': 'Password min 6 chars'}), 400
    users = load_users()
    if user_id not in users:
        return jsonify({'success': False, 'error': 'Utilisateur introuvable'}), 404
    users[user_id]['password'] = hash_password(new_pw)
    save_users(users)
    return jsonify({'success': True})

# ── HELPER pour récupérer le user_id courant ────────────────

def current_user_id():
    return current_user_data().get('user_id', 'default')

# ── STATS ───────────────────────────────────────────────────

@app.route('/api/stats', methods=['GET'])
@require_auth
def get_stats():
    stats = load_stats(current_user_id())
    accounts = load_accounts(current_user_id())
    stats['accounts'] = len(accounts)
    return jsonify({'success': True, 'stats': stats})

@app.route('/api/stats/reset', methods=['POST'])
@require_auth
def reset_stats():
    save_stats({"swipes": 0, "messages": 0, "matches": 0}, current_user_id())
    return jsonify({'success': True})

# --- AUTOMATION ---

@app.route('/api/automation', methods=['GET'])
@require_auth
def get_automation():
    tasks = load_automation(current_user_id())
    # Enrichir avec le statut live
    result = []
    for t in tasks:
        tid = t['id']
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
    task = next((t for t in tasks if t['id'] == task_id), None)
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

# --- STATS HISTORY ---

@app.route('/api/stats/history', methods=['GET'])
@require_auth
def get_stats_history():
    history = load_stats_history(current_user_id())
    return jsonify({'success': True, 'history': history})

@app.route('/api/stats/alltime', methods=['GET'])
@require_auth
def get_stats_alltime():
    history = load_stats_history(current_user_id())
    total = {'swipes': 0, 'messages': 0, 'matches': 0}
    for e in history:
        total['swipes']   += e.get('swipes', 0)
        total['messages'] += e.get('messages', 0)
        total['matches']  += e.get('matches', 0)
    return jsonify({'success': True, 'alltime': total, 'days': len(history)})

# --- MATCH COUNT PER ACCOUNT ---

@app.route('/api/accounts/match-counts', methods=['GET'])
@require_auth
def get_match_counts():
    """
    Compte le vrai nombre de matchs par compte — même méthode que Mass DM :
    tinder_get_matches (message=0) + tinder_get_conversations (message=1)
    dédupliqués par _id. Rien n'est envoyé.
    """
    user_id = current_user_id()
    accs = load_accounts(user_id)
    proxies = get_proxies(user_id)
    result = {}
    for account in accs:
        try:
            tinder_init_session(account, proxies)

            matches_r = tinder_get_matches(account, 100, proxies)
            convs_r   = tinder_get_conversations(account, 100, proxies)

            all_ids = set()

            if matches_r.get('success'):
                for m in matches_r['matches']:
                    mid = m.get('_id')
                    if mid:
                        all_ids.add(mid)

            if convs_r.get('success'):
                for c in convs_r['conversations']:
                    mid = c.get('_id')
                    if mid:
                        all_ids.add(mid)

            result[account['user_id']] = len(all_ids)

            # Persister sur l'objet account pour affichage offline
            account['cached_match_count'] = len(all_ids)

        except Exception as e:
            # Fallback : valeur cachée si disponible
            result[account['user_id']] = account.get('cached_match_count', 0)

    # Sauvegarder les counts cachés sur les comptes
    save_accounts(accs, user_id)

    return jsonify({'success': True, 'counts': result})

# --- ACCOUNTS ---

@app.route('/api/accounts', methods=['GET'])
@require_auth
def get_accounts():
    accounts = load_accounts(current_user_id())
    safe = []
    for a in accounts:
        safe.append({
            'user_id': a.get('user_id'),
            'name': a.get('name'),
            'has_refresh': bool(a.get('refresh_token')),
            'tinder_version': a.get('tinder_version', '17.3.0'),
            'bio': a.get('bio', ''),
            'photo': a.get('photo', ''),
            'age': a.get('age', ''),
            'tags': a.get('tags', []),
            'total_likes':   a.get('total_likes'),
            'total_matches': a.get('total_matches'),
            'cached_match_count': a.get('cached_match_count'),
        })
    return jsonify({'success': True, 'accounts': safe})

@app.route('/api/accounts', methods=['POST'])
@require_auth
def add_account():
    data = request.json
    required = ['token', 'persistent_device_id', 'device_id']
    if not all(k in data for k in required):
        return jsonify({'success': False, 'error': 'Champs requis: token, persistent_device_id, device_id'}), 400

    proxies = get_proxies(current_user_id())

    # Vérifier le token
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

    result = tinder_check_token(temp_account, proxies)
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
    }
    if data.get('refresh_token'):
        account['refresh_token'] = data['refresh_token']

    accounts = load_accounts(current_user_id())
    if any(a['user_id'] == account['user_id'] for a in accounts):
        return jsonify({'success': False, 'error': 'Compte déjà existant'}), 409

    accounts.append(account)
    save_accounts(accounts, current_user_id())
    return jsonify({'success': True, 'name': result['name'], 'user_id': result['user_id']})

@app.route('/api/accounts/<user_id>/tags', methods=['POST'])
@require_auth
def update_account_tags(user_id):
    tags = request.json.get('tags', [])
    accounts = load_accounts(current_user_id())
    for a in accounts:
        if a['user_id'] == user_id:
            a['tags'] = tags
    save_accounts(accounts, current_user_id())
    return jsonify({'success': True})

# --- TAGS ---

@app.route('/api/tags', methods=['GET'])
@require_auth
def get_tags():
    return jsonify({'success': True, 'tags': load_tags(current_user_id())})

@app.route('/api/tags', methods=['POST'])
@require_auth
def create_tag():
    data = request.json or {}
    name = data.get('name', '').strip()
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
            t['name'] = data.get('name', t['name']).strip()
            t['color'] = data.get('color', t['color'])
    save_tags(tags, current_user_id())
    return jsonify({'success': True})

@app.route('/api/tags/<tag_id>', methods=['DELETE'])
@require_auth
def delete_tag(tag_id):
    tags = load_tags(current_user_id())
    tags = [t for t in tags if t['id'] != tag_id]
    save_tags(tags, current_user_id())
    # Supprimer le tag de tous les comptes
    accounts = load_accounts(current_user_id())
    for a in accounts:
        a['tags'] = [tid for tid in a.get('tags', []) if tid != tag_id]
    save_accounts(accounts, current_user_id())
    return jsonify({'success': True})
    accounts = load_accounts(current_user_id())
    accounts = [a for a in accounts if a['user_id'] != user_id]
    save_accounts(accounts, current_user_id())
    return jsonify({'success': True})

@app.route('/api/accounts/check', methods=['POST'])
@require_auth
def check_tokens():
    accounts = load_accounts(current_user_id())
    proxies = get_proxies(current_user_id())
    results = []
    valid_accounts = []
    for account in accounts:
        r = tinder_check_token(account, proxies)
        results.append({'name': account['name'], 'user_id': account['user_id'], 'valid': r['valid']})
        if r['valid']:
            account['bio']   = r.get('bio', account.get('bio', ''))
            account['photo'] = r.get('photo', account.get('photo', ''))
            account['age']   = r.get('age', account.get('age', ''))
            valid_accounts.append(account)
    save_accounts(valid_accounts, current_user_id())
    return jsonify({'success': True, 'results': results})

@app.route('/api/accounts/<user_id>/bio', methods=['POST'])
@require_auth
def update_bio(user_id):
    bio = request.json.get('bio', '')
    accounts = load_accounts(current_user_id())
    account = next((a for a in accounts if a['user_id'] == user_id), None)
    if not account:
        return jsonify({'success': False, 'error': 'Compte introuvable'}), 404
    proxies = get_proxies(current_user_id())
    result = tinder_update_bio(account, bio, proxies)
    if result['success']:
        for a in accounts:
            if a['user_id'] == user_id:
                a['bio'] = bio
        save_accounts(accounts, current_user_id())
    return jsonify(result)

# --- AUTO SWIPE ---

@app.route('/api/swipe/start', methods=['POST'])
@require_auth
def start_swipe():
    data = request.json
    job_id = str(uuid.uuid4())[:8]
    account_ids = data.get('account_ids', [])
    swipe_count  = int(data.get('swipe_count', 50))
    like_pct     = int(data.get('like_percentage', 80))
    mode         = data.get('mode', 'basic')
    parallel     = bool(data.get('parallel', False))

    thread = threading.Thread(
        target=run_auto_swipe,
        args=(job_id, account_ids, swipe_count, like_pct, mode, current_user_id(), parallel),
        daemon=True
    )
    thread.start()
    return jsonify({'success': True, 'job_id': job_id})

@app.route('/api/swipe/status/<job_id>', methods=['GET'])
@require_auth
def swipe_status(job_id):
    if job_id not in swipe_progress:
        return jsonify({'success': False, 'error': 'Job introuvable'}), 404
    return jsonify({'success': True, **swipe_progress[job_id]})

# --- MASS DM ---

@app.route('/api/dm/start', methods=['POST'])
@require_auth
def start_dm():
    data = request.json
    job_id = str(uuid.uuid4())[:8]
    account_ids    = data.get('account_ids', [])
    username       = data.get('username', '')
    social_network = data.get('social_network', 'Instagram')
    mode           = data.get('mode', 'massdm')  # 'massdm' | 'chatting'

    if not username:
        return jsonify({'success': False, 'error': 'Username requis'}), 400

    thread = threading.Thread(
        target=run_mass_dm,
        args=(job_id, account_ids, username, social_network, mode, current_user_id()),
        daemon=True
    )
    thread.start()
    return jsonify({'success': True, 'job_id': job_id})

@app.route('/api/dm/status/<job_id>', methods=['GET'])
@require_auth
def dm_status(job_id):
    if job_id not in dm_progress:
        return jsonify({'success': False, 'error': 'Job introuvable'}), 404
    return jsonify({'success': True, **dm_progress[job_id]})

# --- PROXY ---

@app.route('/api/proxy', methods=['GET'])
@require_auth
def get_proxy():
    return jsonify({'success': True, 'proxy': load_proxy(current_user_id())})

@app.route('/api/proxy', methods=['POST'])
@require_auth
def set_proxy():
    data = request.json
    config = {
        'enabled': data.get('enabled', False),
        'proxy_url': data.get('proxy_url'),
        'rotation_link': data.get('rotation_link')
    }
    save_proxy(config, current_user_id())
    return jsonify({'success': True})

@app.route('/api/proxy/test', methods=['GET'])
@require_auth
def test_proxy():
    proxies = get_proxies(current_user_id())
    ip = get_current_ip(proxies)
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
        ip = get_current_ip(proxies)
        return jsonify({'success': True, 'new_ip': ip})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# --- MATCHES (lecture) ---

@app.route('/api/matches', methods=['GET'])
@require_auth
def get_matches_list():
    accounts = load_accounts(current_user_id())
    proxies = get_proxies(current_user_id())
    all_matches = []
    for account in accounts:
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
    users = load_users()
    # Reset pour tous les utilisateurs si nouveau jour
    for uid in list(users.keys()) + ['default']:
        data = all_data.get(uid, {})
        last_reset = data.get('last_reset', None)
        if last_reset != today:
            all_data[uid] = {'swipes': 0, 'messages': 0, 'matches': 0, 'last_reset': today}
            changed = True

    if changed:
        print(f"🔄 Nouveau jour ({today}) — reset stats de tous les utilisateurs")
        with open(STATS_FILE, 'w') as f:
            json.dump(all_data, f, indent=2)
    else:
        print(f"✅ Stats du jour déjà chargées ({today})")

def load_stats(user_id="default"):
    try:
        with open(STATS_FILE, 'r') as f:
            d = json.load(f).get(str(user_id), {})
            return {
                'swipes':   d.get('swipes', 0),
                'messages': d.get('messages', 0),
                'matches':  d.get('matches', 0),
            }
    except:
        return {'swipes': 0, 'messages': 0, 'matches': 0}

# ============================================================
# LANCEMENT
# ============================================================

if __name__ == '__main__':
    ensure_admin_exists()
    check_and_reset_stats()

    print("🚀 Backend panel démarré sur http://localhost:5001")
    print("📁 Fichiers de données dans le répertoire courant")
    app.run(host='0.0.0.0', port=5002, debug=False)
