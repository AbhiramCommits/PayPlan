from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.plans.views import CheckoutView, InstallmentViewSet, PlanViewSet

router = DefaultRouter()
router.register("plans", PlanViewSet, basename="plan")
router.register("installments", InstallmentViewSet, basename="installment")

urlpatterns = [
    path("checkout/", CheckoutView.as_view(), name="checkout"),
    path("", include(router.urls)),
]
