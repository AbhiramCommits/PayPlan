from django.core.validators import MinValueValidator
from django.db import models


class Product(models.Model):
    sku = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    price_cents = models.BigIntegerField(validators=[MinValueValidator(1)])
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sku"]
        indexes = [models.Index(fields=["active"], name="product_active_idx")]

    def __str__(self):
        return f"{self.sku} — {self.name}"
