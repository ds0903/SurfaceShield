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
from django.core.mail import send_mail, EmailMessage
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
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
    secret = django_settings.TURNSTILE_SECRET_KEY
    if not secret or django_settings.DEBUG:
        return True  # dev — no key or debug mode, skip
    token = request.POST.get('cf-turnstile-response', '')
    if not token:
        return False
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


def _lead_subject(name, service, urgent=False):
    division = _division_from_service(service)
    prefix = '[URGENT] ' if urgent else ''
    return f'{prefix}New Website Lead | {division} | {name}'


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


def csrf_failure(request, reason=''):
    return JsonResponse(
        {'error': 'csrf_failed', 'message': 'Session expired. Please refresh the page and try again.'},
        status=403,
    )


def health(request):
    return JsonResponse({'status': 'ok'})


@ensure_csrf_cookie
def home(request):
    return render(request, 'core/home.html')


@ensure_csrf_cookie
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
            threading.Thread(
                target=_push_to_quoteiq,
                args=(name, phone, email, '', 'contact', msg, False),
                daemon=True,
            ).start()
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
            threading.Thread(
                target=_push_to_quoteiq,
                args=(name, phone, email, full_address, service, full_msg, False),
                daemon=True,
            ).start()
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


def privacy_policy(request):
    return render(request, 'core/privacy_policy.html')


def terms_of_service(request):
    return render(request, 'core/terms_of_service.html')


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
_EMAIL_EXTRACT_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
_PHONE_EXTRACT_RE = re.compile(r'(\+?\d[\d\s\-().]{7,}\d)')
_NAME_FROM_BOT_RE = re.compile(r'(?:Thank you|Thanks|Hello|Hi|Great)[,!\s]+([A-Z][a-z]{1,20})\b')
_EMAIL_PREF_DETECT_RE = re.compile(
    r'prefer.{0,25}email|email.{0,15}only|don.t call|do not call|contact.{0,15}email',
    re.IGNORECASE,
)
_SERVICE_KEYWORDS = [
    ('restoration', ['roof', 'roofing', 'storm', 'hail', 'wind damage', 'shingle', 'gutter',
                     'siding', 'restoration', 'inspection', 'insurance claim']),
    ('exterior',    ['exterior clean', 'soft wash', 'pressure wash', 'house wash',
                     'window clean', 'power wash']),
    ('auto',        ['car detail', 'auto detail', 'vehicle detail', 'ceramic coat',
                     'paint correction', 'detailing']),
    ('interior',    ['interior clean', 'deep clean', 'carpet clean', 'office clean',
                     'move-in', 'move-out', 'move in', 'move out']),
]


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
    phone = params.get('phone', '')
    phone_is_real = bool(re.search(r'\d{6,}', phone))
    email_val = params.get('email', '')
    email_is_real = bool(re.match(r'[^@\s]+@[^@\s]+\.[^@\s]+', email_val))
    return (params if (phone_is_real or email_is_real) else None), clean


def _strip_md(text):
    """Remove markdown formatting from conversation text."""
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)   # **bold** → bold
    text = re.sub(r'^\s*\*\s+', '• ', text, flags=re.MULTILINE)  # * bullet → •
    return text


def _build_conversation(history, user_message, clean_reply):
    lines = []
    for turn in history:
        role = 'Visitor' if turn.get('role') == 'user' else 'Bot'
        lines.append(f"{role}: {_strip_md(turn.get('text', ''))}")
    lines.append(f'Visitor: {_strip_md(user_message)}')
    lines.append(f'Bot: {_strip_md(clean_reply)}')
    return '\n'.join(lines)


def _push_to_quoteiq(name, phone, email, address, service, message, is_urgent):
    api_key = django_settings.QUOTEIQ_API_KEY
    if not api_key:
        return
    parts = name.strip().split(' ', 1)
    first = parts[0]
    last = parts[1] if len(parts) > 1 else ''
    label = '[URGENT] ' if is_urgent else ''
    # Address field expects object; if string provided put it all in street
    addr_parts = str(address).split(',') if address else []
    addr_obj = {'street': addr_parts[0].strip() if addr_parts else '',
                'city':   addr_parts[1].strip() if len(addr_parts) > 1 else '',
                'state':  addr_parts[2].strip() if len(addr_parts) > 2 else '',
                'zip':    addr_parts[3].strip() if len(addr_parts) > 3 else ''}
    payload = json.dumps({
        'user_id':    django_settings.QUOTEIQ_USER_ID,
        'company_id': django_settings.QUOTEIQ_COMPANY_ID,
        'form_id':    django_settings.QUOTEIQ_FORM_ID,
        '_hp': '',
        'data': {
            '1788607942134000_0': first,
            '1788607942134000_1': last,
            '1788607942134000_2': email or '',
            '1788607942134000_3': phone or '',
            '1788607942134000_4': f'{label}Service: {service}\n\n{message}'[:2000],
            '1788608922698_0':    addr_obj,
        },
    }).encode()
    req = urllib.request.Request(
        'https://us-central1-quoteiq-2.cloudfunctions.net/submitFormV2Api',
        data=payload,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type':  'application/json',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            print(f'[QuoteIQ] submitted status={r.status}')
    except Exception as exc:
        print(f'[QuoteIQ] ERROR: {exc}')


def _save_chat_lead_from_tag(params, history, user_message, clean_reply, request):
    name = params.get('name', 'Unknown')
    phone = params.get('phone', '')
    email = params.get('email', '')
    preferred_contact = params.get('preferred_contact', '')
    service = params.get('service', 'general')
    address = params.get('address', '')

    # Normalize phone=none placeholder from email-preferred customers
    if phone.lower() in ('none', 'n/a', '-', ''):
        phone = ''

    # Deduplicate: same phone+service or email+service within last 24h
    day_ago = timezone.now() - timedelta(hours=24)
    if phone:
        if ChatLead.objects.filter(phone=phone, service_interest=service, created_at__gte=day_ago).exists():
            return
    elif email:
        if ChatLead.objects.filter(email=email, service_interest=service, created_at__gte=day_ago).exists():
            return

    conversation = _build_conversation(history, user_message, clean_reply)
    page_url = params.get('page_url', '')
    referrer = params.get('referrer', '')
    utm_source = params.get('utm_source', '')
    utm_medium = params.get('utm_medium', '')
    utm_campaign = params.get('utm_campaign', '')

    do_not_call = preferred_contact.lower() in ('email',) or params.get('do_not_call', '').lower() == 'true'
    is_urgent = params.get('urgency', '').lower() == 'urgent'

    lead = ChatLead.objects.create(
        name=name, phone=phone, email=email, address=address, service_interest=service,
        preferred_contact=preferred_contact, do_not_call=do_not_call, urgency=is_urgent,
        page_url=page_url, referrer=referrer,
        utm_source=utm_source, utm_medium=utm_medium, utm_campaign=utm_campaign,
        conversation=conversation,
    )
    # Store lead id in session so subsequent messages update the conversation
    leads_in_session = request.session.get('chat_lead_ids', [])
    leads_in_session.append(lead.pk)
    request.session['chat_lead_ids'] = leads_in_session

    # Push to QuoteIQ CRM in background thread (non-blocking)
    threading.Thread(
        target=_push_to_quoteiq,
        args=(name, phone, email, address, service, clean_reply, is_urgent),
        daemon=True,
    ).start()

    now = timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')
    subject = _lead_subject(name, service, urgent=is_urgent)
    body = (
        f'{"🚨 URGENT — Active water intrusion or emergency reported\n\n" if is_urgent else ""}'
        f'New Chat Lead (AI-detected)\n\n'
        f'Name: {name}\n'
        f'Phone: {phone or "—"}\n'
        f'Email: {email or "—"}\n'
        f'Preferred Contact: {preferred_contact or "—"}\n'
        f'Do Not Call: {"YES — contact by email only" if do_not_call else "No"}\n'
        f'Service: {service}\n'
        f'\n— Technical Info —\n'
        f'Date/Time: {now}\n'
        f'Page: {page_url or "—"}\n'
        f'Referrer: {referrer or "—"}\n'
        f'UTM Source: {utm_source or "—"}\n'
        f'UTM Medium: {utm_medium or "—"}\n'
        f'UTM Campaign: {utm_campaign or "—"}\n'
        f'\nFull conversation attached.'
    )
    try:
        msg = EmailMessage(
            subject=subject,
            body=body,
            from_email=django_settings.EMAIL_HOST_USER,
            to=[django_settings.NOTIFICATION_EMAIL],
        )
        filename = f'chat_{name.replace(" ", "_")}_{timezone.now().strftime("%Y%m%d_%H%M%S")}.txt'
        msg.attach(filename, conversation, 'text/plain')
        msg.send(fail_silently=True)
    except Exception:
        pass


def _update_lead_conversations(request, history, user_message, clean_reply):
    """Update conversation + late-arriving contact fields for all leads in this session."""
    lead_ids = request.session.get('chat_lead_ids', [])
    if not lead_ids:
        return
    conversation = _build_conversation(history, user_message, clean_reply)
    try:
        # Scan full history for any new email / preference info that arrived after lead was saved
        all_turns = list(history) + [{'role': 'user', 'text': user_message}]
        late_email, late_pref = '', ''
        for turn in all_turns:
            if turn.get('role') == 'user':
                txt = turn.get('text', '')
                if not late_email:
                    m = _EMAIL_EXTRACT_RE.search(txt)
                    if m:
                        late_email = m.group(0)
                if not late_pref and _EMAIL_PREF_DETECT_RE.search(txt):
                    late_pref = 'email'

        update_fields = {'conversation': conversation}
        if late_email:
            update_fields['email'] = late_email
        if late_pref:
            update_fields['preferred_contact'] = late_pref
            update_fields['do_not_call'] = True

        ChatLead.objects.filter(pk__in=lead_ids).update(**update_fields)
    except Exception:
        pass


def _extract_lead_from_history(history, current_user_msg, current_bot_reply=''):
    """Scan full conversation for name+contact without relying on AI [LEAD:] tag.
    Returns (name, phone, email, preferred_contact, service) — all strings, may be empty.
    """
    # Build list of all turns including current exchange
    all_turns = list(history) + [
        {'role': 'user', 'text': current_user_msg},
        {'role': 'bot',  'text': current_bot_reply},
    ]

    email, phone, name, preferred_contact, service = '', '', '', '', 'general'

    # Email — scan user messages only
    for turn in all_turns:
        if turn.get('role') == 'user':
            m = _EMAIL_EXTRACT_RE.search(turn.get('text', ''))
            if m:
                email = m.group(0)
                break

    # Phone — scan user messages, skip if text also contains email (avoid false match)
    for turn in all_turns:
        if turn.get('role') == 'user':
            txt = turn.get('text', '')
            if _EMAIL_EXTRACT_RE.search(txt):
                continue  # this turn is about email, not phone
            m = _PHONE_EXTRACT_RE.search(txt)
            if m:
                phone = m.group(1).strip()
                break

    # Name — bot typically says "Thank you, Max." or "Hello, John!"
    for turn in all_turns:
        if turn.get('role') == 'bot':
            m = _NAME_FROM_BOT_RE.search(turn.get('text', ''))
            if m:
                name = m.group(1)
                break

    # Preferred contact
    for turn in all_turns:
        if turn.get('role') == 'user':
            if _EMAIL_PREF_DETECT_RE.search(turn.get('text', '')):
                preferred_contact = 'email'
                break

    # Service — scan all text combined
    all_text = ' '.join(t.get('text', '').lower() for t in all_turns)
    for svc, keywords in _SERVICE_KEYWORDS:
        if any(k in all_text for k in keywords):
            service = svc
            break

    return name, phone, email, preferred_contact, service


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

    # Extract already-collected visitor data from full history
    collected_phone, collected_name, collected_email, collected_pref = '', '', '', ''
    for turn in history:
        txt = turn.get('text', '')
        role = turn.get('role', '')
        if role == 'user':
            if not collected_email:
                m = _EMAIL_EXTRACT_RE.search(txt)
                if m:
                    collected_email = m.group(0)
            if not collected_phone and not _EMAIL_EXTRACT_RE.search(txt):
                m = _PHONE_EXTRACT_RE.search(txt)
                if m:
                    collected_phone = m.group(1).strip()
            if not collected_pref and _EMAIL_PREF_DETECT_RE.search(txt):
                collected_pref = 'email'
        elif role == 'bot' and not collected_name:
            m = _NAME_FROM_BOT_RE.search(txt)
            if m:
                collected_name = m.group(1)

    # Build context note injected into system prompt so AI doesn't re-ask
    context_note = ''
    parts_note = []
    if collected_name:
        parts_note.append(f'name={collected_name}')
    if collected_phone:
        parts_note.append(f'phone={collected_phone}')
    if collected_email:
        parts_note.append(f'email={collected_email}')
    if collected_pref:
        parts_note.append(f'preferred_contact={collected_pref}')
    if parts_note:
        context_note = (
            f'\n\n[SYSTEM NOTE: Visitor already provided {", ".join(parts_note)}. '
            f'Do NOT ask for any of this information again in this conversation.]'
        )

    contents = []
    for turn in history:
        role = 'user' if turn.get('role') == 'user' else 'model'
        contents.append({'role': role, 'parts': [{'text': turn.get('text', '')}]})
    contents.append({'role': 'user', 'parts': [{'text': user_message}]})

    payload_obj = {
        'system_instruction': {'parts': [{'text': _SYSTEM_PROMPT + context_note}]},
        'contents': contents,
        'generationConfig': {'temperature': 0.7, 'maxOutputTokens': 500},
    }

    def _call(m, key):
        url = f'https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}'
        data = json.dumps(payload_obj).encode()
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
        candidates = result.get('candidates', [])
        if not candidates:
            raise ValueError('No candidates in Gemini response')
        candidate = candidates[0]
        # Handle safety blocks or empty content
        finish_reason = candidate.get('finishReason', '')
        if finish_reason == 'SAFETY':
            return "I'm sorry, I can't respond to that. Please call us at +1 (216) 280-1855 for assistance."
        parts = candidate.get('content', {}).get('parts', [])
        if not parts:
            raise ValueError('Empty content in Gemini response')
        return parts[0].get('text', '').strip()

    def _process_reply(raw_reply):
        lead_params, clean_reply = _parse_lead_tag(raw_reply)
        tag_found = bool(lead_params)
        if lead_params:
            lead_params.update(tracking)
            try:
                _save_chat_lead_from_tag(lead_params, history, user_message, clean_reply, request)
            except Exception:
                pass

        # FALLBACK: AI emitted no tag → scan history for name+contact and save lead.
        # DB dedup in _save_chat_lead_from_tag prevents duplicates.
        if not tag_found:
            try:
                fb_name, fb_phone, fb_email, fb_pref, fb_service = _extract_lead_from_history(
                    history, user_message, raw_reply
                )
                if fb_name and (fb_phone or fb_email):
                    fb_params = {
                        'name': fb_name,
                        'phone': fb_phone or 'none',
                        'email': fb_email,
                        'service': fb_service,
                        'preferred_contact': fb_pref,
                    }
                    fb_params.update(tracking)
                    visible_reply = clean_reply if clean_reply else _LEAD_TAG_RE.sub('', raw_reply).strip()
                    _save_chat_lead_from_tag(
                        fb_params, history, user_message, visible_reply, request
                    )
            except Exception:
                pass

        # Update conversation for all leads already saved in this session
        try:
            _update_lead_conversations(request, history, user_message,
                                       clean_reply if clean_reply else _LEAD_TAG_RE.sub('', raw_reply).strip())
        except Exception:
            pass
        # If AI wrote only the tag with no message text, return a confirmation
        final = clean_reply if clean_reply else _LEAD_TAG_RE.sub('', raw_reply).strip()
        if not final:
            final = "Thank you! We've received your information and will be in touch shortly. You can also call us at +1 (216) 280-1855."

        # Intercept generic "Is there anything else" when we know the visitor's name+contact
        # Replace with contextual follow-up
        _generic_re = re.compile(
            r'is there (anything|something) else i can (help|assist)',
            re.IGNORECASE,
        )
        _all_hist_text = ' '.join(t.get('text', '').lower() for t in history) + ' ' + user_message.lower()
        _intercept_svc_info = {
            'restoration': ('roof inspection',   'gutters, siding, or exterior soft washing'),
            'exterior':    ('exterior cleaning', 'roof cleaning or window washing'),
            'auto':        ('auto detailing',    'ceramic coating or interior detailing'),
            'interior':    ('interior cleaning', 'deep cleaning or move-in/out service'),
        }
        _detected_svc = 'general'
        for _svc_key, _kw_list in _SERVICE_KEYWORDS:
            if any(k in _all_hist_text for k in _kw_list):
                _detected_svc = _svc_key
                break
        _svc_label, _related = _intercept_svc_info.get(
            _detected_svc, ('your request', 'our full range of services')
        )
        # prefer email if visitor stated that preference, regardless of phone in history
        _contact_method = 'email' if (collected_pref == 'email' or (collected_email and not collected_phone)) else 'phone'

        # Intercept 1: generic "Is there anything else" → contextual follow-up
        if _generic_re.search(final) and collected_name and (collected_phone or collected_email):
            final = (
                f"No problem, {collected_name}! Our team will reach out to you via {_contact_method} "
                f"regarding your {_svc_label}. By the way — many of our customers also appreciate "
                f"our {_related}. Would either of those be of interest to you?"
            )

        # Intercept 2: bot asks for name when we already know it → replace with contextual reply
        _ask_name_re = re.compile(r'provide your name|your name and|what.s your name', re.IGNORECASE)
        if _ask_name_re.search(final) and collected_name and (collected_phone or collected_email):
            final = (
                f"Of course, {collected_name}! I already have your details on file. "
                f"For your {_svc_label}, our team will contact you via {_contact_method}. "
                f"Is there anything specific about the {_svc_label} you'd like to know?"
            )

        return final

    # Try primary model — rotate through ALL keys on any error
    keys = django_settings.GEMINI_KEYS or [django_settings.GEMINI_API_KEY]
    last_err = None
    for _ in range(len(keys)):
        key = _key_manager.next_key()
        key_label = f'...{key[-6:]}' if key else 'empty'
        try:
            raw = _call(model, key)
            print(f'[Gemini] OK model={model} key={key_label}')
            return JsonResponse({'reply': _process_reply(raw)})
        except urllib.error.HTTPError as e:
            if e.code in (429, 403, 400):
                _key_manager.mark_failed(key)
                print(f'[Gemini] HTTP {e.code} key={key_label} → marked failed, trying next')
            else:
                print(f'[Gemini] HTTP {e.code} key={key_label} → trying next')
            last_err = e
        except Exception as e:
            print(f'[Gemini] ERROR key={key_label} → {e} → trying next')
            last_err = e

    # Fallback model — rotate through ALL keys on any error
    print(f'[Gemini] All primary keys failed, switching to fallback model={fallback_model}')
    for _ in range(len(keys)):
        key = _key_manager.next_key()
        key_label = f'...{key[-6:]}' if key else 'empty'
        try:
            raw = _call(fallback_model, key)
            print(f'[Gemini] OK fallback model={fallback_model} key={key_label}')
            return JsonResponse({'reply': _process_reply(raw)})
        except urllib.error.HTTPError as e:
            if e.code in (429, 403, 400):
                _key_manager.mark_failed(key)
                print(f'[Gemini] Fallback HTTP {e.code} key={key_label} → marked failed, trying next')
            else:
                print(f'[Gemini] Fallback HTTP {e.code} key={key_label} → trying next')
            last_err = e
        except Exception as e:
            print(f'[Gemini] Fallback ERROR key={key_label} → {e} → trying next')
            last_err = e

    err_msg = f'Gemini error {last_err.code}' if isinstance(last_err, urllib.error.HTTPError) else str(last_err)
    print(f'[Gemini] FATAL all keys exhausted: {err_msg}')
    return JsonResponse({'error': err_msg}, status=502)
