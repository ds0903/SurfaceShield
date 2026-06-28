from django.db import models


class ServicePage(models.Model):
    SERVICE_CHOICES = [
        ('restoration', 'Surface Shield Restoration'),
        ('exterior', 'Surface Shield Exterior'),
        ('auto', 'Surface Shield Auto'),
        ('interior', 'Surface Shield Interior'),
    ]
    slug = models.CharField(max_length=50, choices=SERVICE_CHOICES, unique=True)
    title = models.CharField(max_length=200)
    tagline = models.CharField(max_length=300)
    description = models.TextField()
    hero_image = models.ImageField(upload_to='services/', blank=True, null=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.title
