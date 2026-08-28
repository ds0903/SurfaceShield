from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie


@ensure_csrf_cookie
def restoration(request):
    return render(request, 'services/restoration.html')


@ensure_csrf_cookie
def exterior(request):
    return render(request, 'services/exterior.html')


@ensure_csrf_cookie
def auto(request):
    return render(request, 'services/auto.html')


@ensure_csrf_cookie
def interior(request):
    return render(request, 'services/interior.html')


@ensure_csrf_cookie
def storm_damage(request):
    return render(request, 'services/storm_damage.html')
