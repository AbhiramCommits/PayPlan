from django.urls import path

from apps.ops.views import (
    AdjustLimitView,
    OpsMemberAuditView,
    OpsMemberDetailView,
    OpsMemberSearchView,
    RescheduleInstallmentView,
    WaiveInstallmentView,
)

urlpatterns = [
    path("members/", OpsMemberSearchView.as_view(), name="ops-member-search"),
    path("members/<int:pk>/", OpsMemberDetailView.as_view(), name="ops-member-detail"),
    path("members/<int:pk>/audit/", OpsMemberAuditView.as_view(), name="ops-member-audit"),
    path("members/<int:pk>/limit/", AdjustLimitView.as_view(), name="ops-adjust-limit"),
    path(
        "installments/<int:pk>/waive/",
        WaiveInstallmentView.as_view(),
        name="ops-waive-installment",
    ),
    path(
        "installments/<int:pk>/reschedule/",
        RescheduleInstallmentView.as_view(),
        name="ops-reschedule-installment",
    ),
]
