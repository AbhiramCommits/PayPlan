from django.contrib import admin

from apps.catalog.models import Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["sku", "name", "price_cents", "active", "created_at"]
    list_filter = ["active"]
    search_fields = ["sku", "name"]
    list_editable = ["active"]
