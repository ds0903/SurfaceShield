from django.conf import settings


def turnstile(request):
    return {'turnstile_site_key': settings.TURNSTILE_SITE_KEY}
