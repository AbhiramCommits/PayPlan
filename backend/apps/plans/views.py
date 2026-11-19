from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.serializers import MemberMeSerializer
from apps.plans.models import Installment, InstallmentPlan
from apps.plans.serializers import (
    CheckoutSerializer,
    InstallmentSerializer,
    PlanDetailSerializer,
    PlanSummarySerializer,
)
from apps.plans.services import CheckoutDeclined, InvalidPlanTerms, checkout


def member_for(user):
    return getattr(user, "member", None)


class MemberScopedQuerysetMixin:
    """Every list/detail query is hard-scoped to the authenticated member."""

    member_field = "member"

    def get_queryset(self):
        member = member_for(self.request.user)
        if member is None:
            return self.queryset.none()
        return self.queryset.filter(**{self.member_field: member})


class PlanViewSet(MemberScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = InstallmentPlan.objects.select_related("order", "order__product").prefetch_related(
        "installments"
    )
    filterset_fields = ["status", "cadence"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return PlanDetailSerializer
        return PlanSummarySerializer


class InstallmentViewSet(MemberScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = InstallmentSerializer
    queryset = Installment.objects.select_related("plan").all()
    member_field = "plan__member"
    filterset_fields = ["status", "plan"]
    ordering_fields = ["due_date", "sequence"]
    ordering = ["due_date"]


class CheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        member = member_for(request.user)
        if member is None:
            return Response({"detail": "No member profile for this user."}, status=404)
        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            result = checkout(
                member=member,
                product=data["product"],
                qty=data["qty"],
                n=data["num_installments"],
                cadence=data["cadence"],
                start_date=data.get("start_date"),
            )
        except CheckoutDeclined as exc:
            return Response(
                {
                    "error": {
                        "code": exc.code,
                        "message": str(exc),
                        "required_cents": exc.required_cents,
                        "available_cents": exc.available_cents,
                    }
                },
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )
        except InvalidPlanTerms as exc:
            return Response(
                {"error": {"code": exc.code, "message": str(exc)}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        plan = (
            InstallmentPlan.objects.select_related("order", "order__product")
            .prefetch_related("installments")
            .get(pk=result.plan.pk)
        )
        return Response(
            {
                "order": {
                    "id": result.order.id,
                    "status": result.order.status,
                    "total_cents": result.order.total_cents,
                },
                "plan": PlanDetailSerializer(plan).data,
                "member": MemberMeSerializer(member).data,
            },
            status=status.HTTP_201_CREATED,
        )


class PlanDetailByPkView(APIView):
    """Explicit 404 (not 403) for another member's plan — no ID enumeration."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        member = member_for(request.user)
        plan = get_object_or_404(
            InstallmentPlan.objects.select_related("order", "order__product").prefetch_related(
                "installments"
            ),
            pk=pk,
            member=member,
        )
        return Response(PlanDetailSerializer(plan).data)
