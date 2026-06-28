from django.shortcuts import render, redirect
from django.contrib import messages
from .models import ContactMessage


def home(request):
    return render(request, 'core/home.html')


def about(request):
    return render(request, 'core/about.html')


def contact(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        service = request.POST.get('service', '').strip()
        msg = request.POST.get('message', '').strip()
        if name and email and msg:
            ContactMessage.objects.create(
                name=name, email=email, phone=phone, service=service, message=msg
            )
            messages.success(request, 'Your message has been sent! We will contact you shortly.')
            return redirect('contact')
        else:
            messages.error(request, 'Please fill in all required fields.')
    return render(request, 'core/contact.html')


def request_information(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        service = request.POST.get('service', '').strip()
        msg = request.POST.get('message', '').strip()
        address = request.POST.get('address', '').strip()
        city = request.POST.get('city', '').strip()
        state = request.POST.get('state', '').strip()
        zip_code = request.POST.get('zip', '').strip()
        heard_from = request.POST.get('heard_from', '').strip()
        full_address = f"{address}, {city}, {state} {zip_code}".strip(', ')
        full_msg = f"Address: {full_address}\nHeard from: {heard_from}\n\n{msg}"
        if name and phone:
            ContactMessage.objects.create(
                name=name, email=email, phone=phone, service=service, message=full_msg
            )
            messages.success(request, 'Thank you! We will get back to you soon.')
            return redirect('request_information')
        else:
            messages.error(request, 'Name and phone are required.')
    return render(request, 'core/request_information.html')


def page_not_found(request, exception):
    return render(request, 'core/404.html', status=404)
