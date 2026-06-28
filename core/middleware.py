from .models import SiteVisit


class VisitorTrackingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        skip = any(request.path.startswith(p) for p in ['/admin', '/static', '/media'])
        if request.method == 'GET' and response.status_code == 200 and not skip:
            ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
            if not ip:
                ip = request.META.get('REMOTE_ADDR', '')
            SiteVisit.objects.create(path=request.path, ip_address=ip)
        return response
