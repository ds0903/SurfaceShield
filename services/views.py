from django.shortcuts import render


def restoration(request):
    return render(request, 'services/restoration.html')


def exterior(request):
    return render(request, 'services/exterior.html')


def auto(request):
    return render(request, 'services/auto.html')


def interior(request):
    return render(request, 'services/interior.html')
