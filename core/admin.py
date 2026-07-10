from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.core.mail import EmailMessage
from django.utils import timezone
from django.utils.html import format_html, mark_safe
from django.urls import path
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages as admin_messages

from .models import ContactMessage, Newsletter, NewsletterCampaign, SiteVisit, ChatLead


# ── Patch admin index to inject dashboard stats ──
def _patch_admin_index():
    from django.contrib.admin import AdminSite
    _orig = AdminSite.index

    def index(self, request, extra_context=None):
        today = timezone.now().date()
        extra_context = extra_context or {}
        try:
            extra_context.update({
                'visitors_today': SiteVisit.objects.filter(visited_at__date=today).count(),
                'visitors_total': SiteVisit.objects.count(),
                'inquiries_today': ContactMessage.objects.filter(created_at__date=today).count(),
                'inquiries_total': ContactMessage.objects.count(),
                'subscribers_total': Newsletter.objects.filter(is_active=True).count(),
                'unread_inquiries': ContactMessage.objects.filter(is_read=False).count(),
                'recent_inquiries': ContactMessage.objects.order_by('-created_at')[:10],
            })
        except Exception:
            pass
        return _orig(self, request, extra_context)

    AdminSite.index = index

_patch_admin_index()


# ── ContactMessage ──
@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('name_badge', 'email', 'phone_fmt', 'service_badge', 'how_heard_badge',
                    'subscribe_badge', 'created_at_fmt', 'read_badge')
    list_filter = ('is_read', 'subscribe', 'service')
    search_fields = ('name', 'email', 'phone')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)
    list_per_page = 25

    def name_badge(self, obj):
        initials = ''.join(p[0].upper() for p in obj.name.split()[:2]) if obj.name else '?'
        return format_html(
            '<div style="display:flex;align-items:center;gap:10px;">'
            '<div style="width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,#1a9ed4,#1a3a6b);'
            'color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px;flex-shrink:0;">{}</div>'
            '<div style="font-weight:600;color:#1a1a2e;">{}</div>'
            '</div>',
            initials, obj.name
        )
    name_badge.short_description = 'Name'

    def phone_fmt(self, obj):
        return format_html('<span style="white-space:nowrap;">{}</span>', obj.phone or '—')
    phone_fmt.short_description = 'Phone'

    def service_badge(self, obj):
        colors = {
            'restoration': ('#fff0f0', '#c62828'),
            'exterior':    ('#e3f2fd', '#1565c0'),
            'auto':        ('#e8f5e9', '#2e7d32'),
            'interior':    ('#f3e5f5', '#6a1b9a'),
        }
        bg, text = colors.get(obj.service, ('#f5f5f5', '#555'))
        return format_html(
            '<span style="background:{};color:{};padding:4px 10px;border-radius:20px;'
            'font-size:11px;font-weight:600;white-space:nowrap;">{}</span>',
            bg, text, obj.service.title() if obj.service else '—'
        )
    service_badge.short_description = 'Service'

    def how_heard_badge(self, obj):
        return format_html(
            '<span style="background:#f0f0f0;color:#555;padding:3px 9px;border-radius:12px;font-size:11px;">{}</span>',
            obj.how_heard or '—'
        )
    how_heard_badge.short_description = 'How Heard'

    def subscribe_badge(self, obj):
        if obj.subscribe:
            return mark_safe('<span style="background:#e8f5e9;color:#2e7d32;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600;">&#10004; Yes</span>')
        return mark_safe('<span style="background:#f5f5f5;color:#999;padding:3px 10px;border-radius:20px;font-size:11px;">&#10007; No</span>')
    subscribe_badge.short_description = 'Newsletter'

    def created_at_fmt(self, obj):
        return format_html(
            '<span style="color:#555;font-size:12px;white-space:nowrap;">{}</span>',
            obj.created_at.strftime('%b %d, %Y %H:%M') if obj.created_at else '—'
        )
    created_at_fmt.short_description = 'Received'

    def read_badge(self, obj):
        if obj.is_read:
            return mark_safe('<span style="background:#e8f5e9;color:#2e7d32;padding:4px 12px;border-radius:20px;font-size:11px;font-weight:600;">&#10004; Read</span>')
        return mark_safe('<span style="background:#fff3e0;color:#e65100;padding:4px 12px;border-radius:20px;font-size:11px;font-weight:700;">&#9679; New</span>')
    read_badge.short_description = 'Status'
    read_badge.admin_order_field = 'is_read'

    def change_view(self, request, object_id, form_url='', extra_context=None):
        obj = self.get_object(request, object_id)
        if obj and not obj.is_read:
            obj.is_read = True
            obj.save(update_fields=['is_read'])
        return super().change_view(request, object_id, form_url, extra_context)


# ── Newsletter subscribers ──
@admin.register(Newsletter)
class NewsletterAdmin(admin.ModelAdmin):
    list_display = ('email', 'subscribed_at', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('email',)
    ordering = ('-subscribed_at',)


# ── Newsletter campaigns ──
@admin.register(NewsletterCampaign)
class NewsletterCampaignAdmin(admin.ModelAdmin):
    list_display = ('subject', 'sent_at', 'sent_count', 'created_at')
    readonly_fields = ('sent_at', 'sent_count', 'created_at')
    actions = ['send_to_subscribers']

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path('send-preview/<int:campaign_id>/',
                 self.admin_site.admin_view(self.send_preview_view),
                 name='newslettercampaign_send_preview'),
        ]
        return custom + urls

    def send_to_subscribers(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, 'Select exactly one campaign to send.', level=admin_messages.WARNING)
            return
        campaign = queryset.first()
        return redirect(f'/admin/core/newslettercampaign/send-preview/{campaign.pk}/')
    send_to_subscribers.short_description = 'Choose recipients & send'

    def send_preview_view(self, request, campaign_id):
        campaign = get_object_or_404(NewsletterCampaign, pk=campaign_id)
        subscribers = Newsletter.objects.filter(is_active=True).order_by('email')

        if request.method == 'POST':
            selected_emails = request.POST.getlist('recipients')
            if not selected_emails:
                admin_messages.warning(request, 'No recipients selected.')
            else:
                sent_total = 0
                for email_addr in selected_emails:
                    try:
                        msg = EmailMessage(
                            subject=campaign.subject,
                            body=campaign.body,
                            to=[email_addr]
                        )
                        msg.content_subtype = 'html'
                        if campaign.image:
                            msg.attach_file(campaign.image.path)
                        msg.send()
                        sent_total += 1
                    except Exception:
                        pass
                campaign.sent_at = timezone.now()
                campaign.sent_count = (campaign.sent_count or 0) + sent_total
                campaign.save()
                admin_messages.success(request, f'Sent to {sent_total} subscriber(s).')
                return redirect('/admin/core/newslettercampaign/')

        context = {
            **self.admin_site.each_context(request),
            'title': f'Send: {campaign.subject}',
            'campaign': campaign,
            'subscribers': subscribers,
            'total': subscribers.count(),
        }
        return render(request, 'admin/core/newslettercampaign/send_preview.html', context)


# ── Chat Leads ──
@admin.register(ChatLead)
class ChatLeadAdmin(admin.ModelAdmin):
    list_display = ('name_badge', 'phone_fmt', 'service_interest', 'created_at_fmt', 'read_badge')
    list_filter = ('is_read',)
    search_fields = ('name', 'phone')
    readonly_fields = ('created_at', 'conversation')
    ordering = ('-created_at',)
    list_per_page = 25

    def name_badge(self, obj):
        initials = ''.join(p[0].upper() for p in obj.name.split()[:2]) if obj.name else '?'
        return format_html(
            '<div style="display:flex;align-items:center;gap:10px;">'
            '<div style="width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,#3a8ee6,#1a3a6b);'
            'color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:13px;flex-shrink:0;">{}</div>'
            '<div style="font-weight:600;color:#1a1a2e;">{}</div>'
            '</div>',
            initials, obj.name
        )
    name_badge.short_description = 'Name'

    def phone_fmt(self, obj):
        return format_html('<a href="tel:{}" style="white-space:nowrap;font-weight:600;">{}</a>', obj.phone, obj.phone)
    phone_fmt.short_description = 'Phone'

    def created_at_fmt(self, obj):
        return format_html('<span style="color:#555;font-size:12px;white-space:nowrap;">{}</span>',
                           obj.created_at.strftime('%b %d, %Y %H:%M') if obj.created_at else '—')
    created_at_fmt.short_description = 'Received'

    def read_badge(self, obj):
        if obj.is_read:
            return mark_safe('<span style="background:#e8f5e9;color:#2e7d32;padding:4px 12px;border-radius:20px;font-size:11px;font-weight:600;">&#10004; Read</span>')
        return mark_safe('<span style="background:#e3f2fd;color:#1565c0;padding:4px 12px;border-radius:20px;font-size:11px;font-weight:700;">&#9679; New Chat</span>')
    read_badge.short_description = 'Status'

    def change_view(self, request, object_id, form_url='', extra_context=None):
        obj = self.get_object(request, object_id)
        if obj and not obj.is_read:
            obj.is_read = True
            obj.save(update_fields=['is_read'])
        return super().change_view(request, object_id, form_url, extra_context)


# ── SiteVisit ──
@admin.register(SiteVisit)
class SiteVisitAdmin(admin.ModelAdmin):
    list_display = ('path', 'ip_address', 'visited_at')
    readonly_fields = ('path', 'ip_address', 'visited_at')
    ordering = ('-visited_at',)
    list_per_page = 50

    def has_add_permission(self, request):
        return False


# ── User ──
admin.site.unregister(User)

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
