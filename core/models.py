from django.db import models


class SiteVisit(models.Model):
    path = models.CharField(max_length=500)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    visited_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-visited_at']

    def __str__(self):
        return f"{self.path} — {self.visited_at:%Y-%m-%d %H:%M}"


class ContactMessage(models.Model):
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    service = models.CharField(max_length=100, blank=True)
    how_heard = models.CharField(max_length=100, blank=True)
    message = models.TextField(blank=True)
    subscribe = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} — {self.email}"


class Newsletter(models.Model):
    email = models.EmailField(unique=True)
    subscribed_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.email


class ChatLead(models.Model):
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=50)
    service_interest = models.CharField(max_length=200, blank=True)
    conversation = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[Chat] {self.name} — {self.phone}"


class NewsletterCampaign(models.Model):
    subject = models.CharField(max_length=300)
    body = models.TextField()
    image = models.ImageField(upload_to='newsletter/', blank=True, null=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.subject
