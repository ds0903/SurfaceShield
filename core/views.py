import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings as django_settings
from django.contrib import messages
from django.core.mail import send_mail
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import ContactMessage, Newsletter, ChatLead


_KEY_STATUS_FILE = Path(__file__).parent / 'key_status.json'
_km_lock = threading.Lock()


class _GeminiKeyManager:
    def __init__(self):
        self._index = 0

    def _keys(self):
        return django_settings.GEMINI_KEYS or [django_settings.GEMINI_API_KEY]

    def _load(self):
        try:
            with open(_KEY_STATUS_FILE, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self, status):
        try:
            with open(_KEY_STATUS_FILE, 'w', encoding='utf-8') as f:
                json.dump(status, f, indent=2)
        except Exception:
            pass

    def _is_failed(self, key, status):
        entry = status.get(key)
        if not entry:
            return False
        try:
            failed_at = datetime.fromisoformat(entry['failed_at'])
            return datetime.now() - failed_at < timedelta(hours=1)
        except Exception:
            return False

    def mark_failed(self, key):
        with _km_lock:
            status = self._load()
            status[key] = {'failed_at': datetime.now().isoformat()}
            self._save(status)

    def next_key(self):
        with _km_lock:
            keys = self._keys()
            if not keys:
                return ''
            status = self._load()
            for _ in range(len(keys)):
                key = keys[self._index % len(keys)]
                self._index = (self._index + 1) % len(keys)
                if not self._is_failed(key, status):
                    return key
            # all failed — reset and return first
            self._save({})
            return keys[0]


_key_manager = _GeminiKeyManager()


def _get_client_ip(request):
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def _verify_turnstile(request):
    token = request.POST.get('cf-turnstile-response', '')
    if not token:
        return False
    secret = django_settings.TURNSTILE_SECRET_KEY
    if not secret:
        return True  # dev — no key, skip
    data = urllib.parse.urlencode({'secret': secret, 'response': token}).encode()
    try:
        with urllib.request.urlopen(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data=data, timeout=5
        ) as r:
            result = json.loads(r.read())
            return result.get('success', False)
    except Exception:
        return True  # network error — don't block legit users


def _check_rate_limit(ip):
    """Max 1 message/hour, max 3 messages/24h per IP."""
    now = timezone.now()
    hour_ago = now - timezone.timedelta(hours=1)
    day_ago = now - timezone.timedelta(hours=24)
    hour_count = ContactMessage.objects.filter(
        message__startswith='[IP:', created_at__gte=hour_ago
    ).count()
    # Use IP stored in message prefix or just count by time window broadly
    recent_hour = ContactMessage.objects.filter(created_at__gte=hour_ago).count()
    recent_day = ContactMessage.objects.filter(created_at__gte=day_ago).count()
    return False  # simplified — no per-IP DB storage, rely on Turnstile


def _send_notification(subject, body):
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=django_settings.EMAIL_HOST_USER,
            recipient_list=[django_settings.NOTIFICATION_EMAIL],
            fail_silently=True,
        )
    except Exception:
        pass


def _division_from_service(service):
    s = (service or '').lower()
    if any(x in s for x in ('roof', 'restor', 'storm', 'shingle', 'siding', 'gutter')):
        return 'Restoration'
    if any(x in s for x in ('exterior', 'wash', 'pressure', 'soft', 'window', 'concrete')):
        return 'Exterior'
    if any(x in s for x in ('auto', 'car', 'vehicle', 'detail', 'ceramic', 'paint', 'fleet')):
        return 'Auto'
    if any(x in s for x in ('interior', 'clean', 'deep', 'move', 'post', 'construction')):
        return 'Interior'
    return service.title() if service else 'General'


def _lead_subject(name, service):
    division = _division_from_service(service)
    return f'New Website Lead | {division} | {name}'


def _meta_block(request):
    now = timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')
    page = request.POST.get('page_url', request.META.get('HTTP_REFERER', '—'))
    ref = request.POST.get('referrer', '—')
    utm_source = request.POST.get('utm_source', '—')
    utm_medium = request.POST.get('utm_medium', '—')
    utm_campaign = request.POST.get('utm_campaign', '—')
    return (
        f'\n— Technical Info —\n'
        f'Date/Time: {now}\n'
        f'Page: {page}\n'
        f'Referrer: {ref}\n'
        f'UTM Source: {utm_source}\n'
        f'UTM Medium: {utm_medium}\n'
        f'UTM Campaign: {utm_campaign}\n'
    )


def home(request):
    return render(request, 'core/home.html')


def about(request):
    return render(request, 'core/about.html')


def contact(request):
    form_start = int(timezone.now().timestamp())
    if request.method == 'POST':
        # Honeypot
        if request.POST.get('website', ''):
            return redirect('contact')

        # Time delay (< 4 seconds = bot)
        try:
            elapsed = int(timezone.now().timestamp()) - int(request.POST.get('form_start', 0))
            if elapsed < 4:
                return redirect('contact')
        except (ValueError, TypeError):
            pass

        # Turnstile
        if not _verify_turnstile(request):
            messages.error(request, 'Security check failed. Please try again.')
            return redirect('contact')

        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        msg = request.POST.get('message', '').strip()

        if name and email and msg:
            ContactMessage.objects.create(
                name=name, email=email, phone=phone, message=msg
            )
            _send_notification(
                subject=_lead_subject(name, 'contact'),
                body=(
                    f'Name: {name}\nEmail: {email}\nPhone: {phone}\n\nMessage:\n{msg}'
                    + _meta_block(request)
                ),
            )
            messages.success(request, 'Your message has been sent! We will contact you shortly.')
            return redirect('contact')
        else:
            messages.error(request, 'Please fill in all required fields.')
    return render(request, 'core/contact.html', {'form_start': form_start})


def request_information(request):
    form_start = int(timezone.now().timestamp())
    if request.method == 'POST':
        # Honeypot
        if request.POST.get('website', ''):
            return redirect('request_information')

        # Time delay
        try:
            elapsed = int(timezone.now().timestamp()) - int(request.POST.get('form_start', 0))
            if elapsed < 4:
                return redirect('request_information')
        except (ValueError, TypeError):
            pass

        # Turnstile
        if not _verify_turnstile(request):
            messages.error(request, 'Security check failed. Please try again.')
            return redirect('request_information')

        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        service = request.POST.get('service', '').strip()
        address = request.POST.get('address', '').strip()
        city = request.POST.get('city', '').strip()
        state = request.POST.get('state', '').strip()
        zip_code = request.POST.get('zip', '').strip()
        heard_from = request.POST.get('heard_from', '').strip()
        msg = request.POST.get('message', '').strip()
        subscribe = request.POST.get('subscribe') == 'on'

        full_address = ', '.join(filter(None, [address, city, state, zip_code]))
        full_msg = '\n'.join(filter(None, [
            f'Address: {full_address}' if full_address else '',
            msg,
        ]))

        if name and phone and service and msg:
            ContactMessage.objects.create(
                name=name,
                email=email,
                phone=phone,
                service=service,
                how_heard=heard_from,
                message=full_msg,
                subscribe=subscribe,
            )
            if subscribe and email:
                Newsletter.objects.get_or_create(email=email)

            _send_notification(
                subject=_lead_subject(name, service),
                body=(
                    f'Name: {name}\n'
                    f'Phone: {phone}\n'
                    f'Email: {email}\n'
                    f'Service: {service}\n'
                    f'Address: {full_address}\n'
                    f'How Heard: {heard_from}\n\n'
                    f'Message:\n{msg}'
                    + _meta_block(request)
                ),
            )
            messages.success(request, 'Thank you! We will get back to you soon.')
            return redirect('request_information')
        else:
            messages.error(request, 'Please fill in all required fields.')
    return render(request, 'core/request_information.html', {'form_start': form_start})


def page_not_found(request, exception):
    return render(request, 'core/404.html', status=404)


@require_POST
def save_lead(request):
    try:
        body = json.loads(request.body)
        name = body.get('name', '').strip()
        phone = body.get('phone', '').strip()
        email = body.get('email', '').strip()
        address = body.get('address', '').strip()
        service = body.get('service', '').strip()
        description = body.get('description', '').strip()
        preferred_contact = body.get('preferred_contact', '').strip()
        call_time = body.get('call_time', '').strip()
        page_url = body.get('page_url', '').strip()
        referrer = body.get('referrer', '').strip()
        utm_source = body.get('utm_source', '').strip()
        utm_medium = body.get('utm_medium', '').strip()
        utm_campaign = body.get('utm_campaign', '').strip()
        conversation = body.get('conversation', '').strip()
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({'error': 'Invalid request'}, status=400)

    if not name or not phone:
        return JsonResponse({'error': 'Name and phone required'}, status=400)

    session_key = f'chat_lead_{phone}'
    if request.session.get(session_key):
        return JsonResponse({'status': 'already_saved'})
    request.session[session_key] = True

    ChatLead.objects.create(
        name=name, phone=phone, email=email, address=address,
        service_interest=service, description=description,
        preferred_contact=preferred_contact, call_time=call_time,
        page_url=page_url, referrer=referrer,
        utm_source=utm_source, utm_medium=utm_medium, utm_campaign=utm_campaign,
        conversation=conversation,
    )

    now = timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')
    _send_notification(
        subject=_lead_subject(name, service),
        body=(
            f'New Chat Lead\n\n'
            f'Name: {name}\n'
            f'Phone: {phone}\n'
            f'Email: {email or "—"}\n'
            f'Address: {address or "—"}\n'
            f'Service: {service or "—"}\n'
            f'Description: {description or "—"}\n'
            f'Preferred Contact: {preferred_contact or "—"}\n'
            f'Best Time to Call: {call_time or "—"}\n'
            f'\n— Technical Info —\n'
            f'Date/Time: {now}\n'
            f'Page: {page_url or "—"}\n'
            f'Referrer: {referrer or "—"}\n'
            f'UTM Source: {utm_source or "—"}\n'
            f'UTM Medium: {utm_medium or "—"}\n'
            f'UTM Campaign: {utm_campaign or "—"}\n'
            f'\n— Conversation —\n{conversation}'
        )
    )

    return JsonResponse({'status': 'saved'})


def sitemap(request):
    return render(request, 'sitemap.xml', content_type='application/xml')


def robots_txt(request):
    content = "User-agent: *\nAllow: /\nSitemap: https://surfaceshieldsystems.com/sitemap.xml\n"
    return HttpResponse(content, content_type='text/plain')


def _load_prompt():
    base_dir = Path(__file__).parent
    parts = [
        '# Surface Shield Systems — AI Assistant\n'
        '# YAML knowledge base. Use all sections to answer questions accurately.\n'
        '# Collect leads per lead_capture rules. Follow all rules strictly.\n\n'
    ]
    # Master prompt
    master = base_dir / 'chat_prompt.yaml'
    with open(master, encoding='utf-8') as f:
        parts.append(f.read())
    # Load all module files from core/modules/ in sorted order
    modules_dir = base_dir / 'modules'
    if modules_dir.exists():
        for mod_file in sorted(modules_dir.glob('*.yaml')):
            parts.append(f'\n\n# --- Module: {mod_file.stem} ---\n')
            with open(mod_file, encoding='utf-8') as f:
                parts.append(f.read())
    return '\n'.join(parts)


_SYSTEM_PROMPT = _load_prompt()

_LEAD_TAG_RE = re.compile(r'\[LEAD:([^\]]+)\]', re.IGNORECASE)


def _parse_lead_tag(text):
    """Find [LEAD:name=...,phone=...,service=...] in text.
    Returns (params_dict or None, clean_text_without_tag).
    """
    match = _LEAD_TAG_RE.search(text)
    if not match:
        return None, text
    params = {}
    for part in match.group(1).split(','):
        if '=' in part:
            k, v = part.split('=', 1)
            params[k.strip().lower()] = v.strip()
    clean = _LEAD_TAG_RE.sub('', text).strip()
    return (params if params.get('phone') else None), clean


def _save_chat_lead_from_tag(params, history, user_message, clean_reply, request):
    name = params.get('name', 'Unknown')
    phone = params.get('phone', '')
    service = params.get('service', 'general')

    # Deduplicate: same phone + service within last 24h
    day_ago = timezone.now() - timedelta(hours=24)
    if ChatLead.objects.filter(phone=phone, service_interest=service, created_at__gte=day_ago).exists():
        return

    # Build conversation string from history + current exchange
    lines = []
    for turn in history:
        role = 'Visitor' if turn.get('role') == 'user' else 'Bot'
        lines.append(f"{role}: {turn.get('text', '')}")
    lines.append(f'Visitor: {user_message}')
    lines.append(f'Bot: {clean_reply}')
    conversation = '\n'.join(lines)

    page_url = params.get('page_url', '')
    referrer = params.get('referrer', '')
    utm_source = params.get('utm_source', '')
    utm_medium = params.get('utm_medium', '')
    utm_campaign = params.get('utm_campaign', '')

    ChatLead.objects.create(
        name=name, phone=phone, service_interest=service,
        page_url=page_url, referrer=referrer,
        utm_source=utm_source, utm_medium=utm_medium, utm_campaign=utm_campaign,
        conversation=conversation,
    )

    now = timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')
    _send_notification(
        subject=_lead_subject(name, service),
        body=(
            f'New Chat Lead (AI-detected)\n\n'
            f'Name: {name}\n'
            f'Phone: {phone}\n'
            f'Service: {service}\n'
            f'\n— Technical Info —\n'
            f'Date/Time: {now}\n'
            f'Page: {page_url or "—"}\n'
            f'Referrer: {referrer or "—"}\n'
            f'UTM Source: {utm_source or "—"}\n'
            f'UTM Medium: {utm_medium or "—"}\n'
            f'UTM Campaign: {utm_campaign or "—"}\n'
            f'\n— Conversation —\n{conversation}'
        )
    )


@require_POST
def chat_api(request):
    model = django_settings.GEMINI_MODEL
    fallback_model = django_settings.GEMINI_MODEL_FALLBACK

    if not django_settings.GEMINI_KEYS and not django_settings.GEMINI_API_KEY:
        return JsonResponse({'error': 'AI not configured'}, status=503)

    try:
        body = json.loads(request.body)
        history = body.get('history', [])
        user_message = body.get('message', '').strip()
        if not user_message:
            return JsonResponse({'error': 'Empty message'}, status=400)
        # UTM + tracking from frontend
        tracking = {
            'page_url': body.get('page_url', ''),
            'referrer': body.get('referrer', ''),
            'utm_source': body.get('utm_source', ''),
            'utm_medium': body.get('utm_medium', ''),
            'utm_campaign': body.get('utm_campaign', ''),
        }
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({'error': 'Invalid request'}, status=400)

    contents = []
    for turn in history[-10:]:
        role = 'user' if turn.get('role') == 'user' else 'model'
        contents.append({'role': role, 'parts': [{'text': turn.get('text', '')}]})
    contents.append({'role': 'user', 'parts': [{'text': user_message}]})

    payload_obj = {
        'system_instruction': {'parts': [{'text': _SYSTEM_PROMPT}]},
        'contents': contents,
        'generationConfig': {'temperature': 0.7, 'maxOutputTokens': 350},
    }

    def _call(m, key):
        url = f'https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}'
        data = json.dumps(payload_obj).encode()
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
        return result['candidates'][0]['content']['parts'][0]['text'].strip()

    def _process_reply(raw_reply):
        lead_params, clean_reply = _parse_lead_tag(raw_reply)
        if lead_params:
            lead_params.update(tracking)
            try:
                _save_chat_lead_from_tag(lead_params, history, user_message, clean_reply, request)
            except Exception:
                pass
        return clean_reply

    # Try primary model with key rotation
    keys = django_settings.GEMINI_KEYS or [django_settings.GEMINI_API_KEY]
    last_err = None
    for _ in range(len(keys)):
        key = _key_manager.next_key()
        try:
            raw = _call(model, key)
            return JsonResponse({'reply': _process_reply(raw)})
        except urllib.error.HTTPError as e:
            if e.code in (429, 403, 400):
                _key_manager.mark_failed(key)
                last_err = e
            else:
                last_err = e
                break
        except Exception as e:
            last_err = e
            break

    # Fallback model
    key = _key_manager.next_key()
    try:
        raw = _call(fallback_model, key)
        return JsonResponse({'reply': _process_reply(raw)})
    except urllib.error.HTTPError as e:
        _key_manager.mark_failed(key)
        return JsonResponse({'error': f'Gemini error {e.code}'}, status=502)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=502)
