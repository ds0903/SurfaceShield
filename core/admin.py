from django.contrib import admin
from .models import ContactMessage, SiteVisit, Newsletter


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'phone', 'service', 'created_at', 'is_read')
    list_filter = ('is_read', 'service', 'created_at')
    search_fields = ('name', 'email', 'message')
    readonly_fields = ('created_at',)
    list_editable = ('is_read',)


@admin.register(SiteVisit)
class SiteVisitAdmin(admin.ModelAdmin):
    list_display = ('path', 'ip_address', 'visited_at')
    list_filter = ('visited_at',)
    readonly_fields = ('path', 'ip_address', 'visited_at')


@admin.register(Newsletter)
class NewsletterAdmin(admin.ModelAdmin):
    list_display = ('email', 'subscribed_at', 'is_active')
    list_filter = ('is_active',)
