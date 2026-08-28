from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('about/', views.about, name='about'),
    path('contact/', views.contact, name='contact'),
    path('request-information/', views.request_information, name='request_information'),
    path('sitemap.xml', views.sitemap, name='sitemap'),
    path('robots.txt', views.robots_txt, name='robots_txt'),
    path('api/chat/', views.chat_api, name='chat_api'),
    path('api/save-lead/', views.save_lead, name='save_lead'),
    path('api/health/', views.health, name='health'),
]
