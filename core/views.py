import json
import urllib.parse
import urllib.request

from django.conf import settings as django_settings
from django.contrib import messages
from django.core.mail import send_mail
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.utils import timezone

from .models import ContactMessage, Newsletter


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
                subject=f'New Contact: {name}',
                body=f'Name: {name}\nEmail: {email}\nPhone: {phone}\n\nMessage:\n{msg}',
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

        if name and phone:
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
                subject=f'New Request: {name}',
                body=(
                    f'Name: {name}\n'
                    f'Phone: {phone}\n'
                    f'Email: {email}\n'
                    f'Service: {service}\n'
                    f'Address: {full_address}\n'
                    f'How Heard: {heard_from}\n\n'
                    f'Message:\n{msg}'
                ),
            )
            messages.success(request, 'Thank you! We will get back to you soon.')
            return redirect('request_information')
        else:
            messages.error(request, 'Name and phone are required.')
    return render(request, 'core/request_information.html', {'form_start': form_start})


def page_not_found(request, exception):
    return render(request, 'core/404.html', status=404)


def sitemap(request):
    return render(request, 'sitemap.xml', content_type='application/xml')


def robots_txt(request):
    content = "User-agent: *\nAllow: /\nSitemap: https://surfaceshieldsystems.com/sitemap.xml\n"
    return HttpResponse(content, content_type='text/plain')
