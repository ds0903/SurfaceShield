from django.urls import path
from . import views

urlpatterns = [
    path('restoration/', views.restoration, name='restoration'),
    path('exterior/', views.exterior, name='exterior'),
    path('auto/', views.auto, name='auto'),
    path('interior/', views.interior, name='interior'),
]
