from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Member, SpendingLimit
from apps.ops.models import OpsAction, OpsAuditLog
from apps.ops.permissions import IsSupportRole
from apps.ops.serializers import (
    AdjustLimitSerializer,
    OpsAuditLogSerializer,
    OpsMemberDetailSerializer,
    OpsMemberSerializer,
    RescheduleSerializer,
    WaiveSerializer,
)
from apps.plans.models import Installment, InstallmentStatus, PlanStatus
from apps.plans.services import (
    available_spending_power,
    current_limit_cents,
    outstanding_cents,
    sync_available,
)


def _audit(actor, member, action, before, after):
    return OpsAuditLog.objects.create(
        actor=actor, member=member, action=action, before=before, after=after
    )


def _installment_snapshot(installment):
    return {
        "installment_id": installment.id,
        "plan_id": installment.plan_id,
        "sequence": installment.sequence,
        "due_date": installment.due_date.isoformat(),
        "amount_cents": installment.amount_cents,
        "amount_paid_cents": installment.amount_paid_cents,
        "status": installment.status,
        "remaining_cents": installment.remaining_cents,
    }


def _maybe_complete_plan(plan):
    if plan.installments.exclude(
        status__in=[InstallmentStatus.PAID, InstallmentStatus.WAIVED]
    ).exists():
        return plan.status
    if plan.status != PlanStatus.COMPLETED:
        plan.status = PlanStatus.COMPLETED
        plan.save(update_fields=["status"])
    return plan.status


class SupportOnlyView(APIView):
    permission_classes = [IsSupportRole]


class OpsMemberSearchView(SupportOnlyView):
    def get(self, request):
        query = request.query_params.get("q", "").strip()
        members = Member.objects.select_related("user").order_by("-created_at")
        if query:
            members = members.filter(
                Q(external_id__icontains=query)
                | Q(user__username__icontains=query)
                | Q(user__email__icontains=query)
                | Q(user__first_name__icontains=query)
                | Q(user__last_name__icontains=query)
            )
        return Response({"results": OpsMemberSerializer(members[:25], many=True).data})


class OpsMemberDetailView(SupportOnlyView):
    def get(self, request, pk):
        member = get_object_or_404(Member.objects.select_related("user"), pk=pk)
        return Response(OpsMemberDetailSerializer(member).data)


class OpsMemberAuditView(SupportOnlyView):
    def get(self, request, pk):
        member = get_object_or_404(Member, pk=pk)
        logs = OpsAuditLog.objects.filter(member=member).select_related("actor")[:100]
        return Response({"results": OpsAuditLogSerializer(logs, many=True).data})


class WaiveInstallmentView(SupportOnlyView):
    @transaction.atomic
    def post(self, request, pk):
        serializer = WaiveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        installment = get_object_or_404(
            Installment.objects.select_for_update().select_related("plan"), pk=pk
        )
        before = _installment_snapshot(installment)
        if installment.status != InstallmentStatus.WAIVED:
            installment.status = InstallmentStatus.WAIVED
            installment.save(update_fields=["status"])
            _maybe_complete_plan(installment.plan)
            sync_available(installment.plan.member)
        installment.refresh_from_db()
        after = _installment_snapshot(installment)
        after["reason"] = serializer.validated_data.get("reason", "")
        after["plan_status"] = installment.plan.status
        audit = _audit(
            request.user,
            installment.plan.member,
            OpsAction.WAIVE_INSTALLMENT,
            before,
            after,
        )
        return Response({"installment": after, "audit_id": audit.id}, status=status.HTTP_200_OK)


class RescheduleInstallmentView(SupportOnlyView):
    @transaction.atomic
    def post(self, request, pk):
        serializer = RescheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_due = serializer.validated_data["due_date"]
        installment = get_object_or_404(
            Installment.objects.select_for_update().select_related("plan"), pk=pk
        )
        before = _installment_snapshot(installment)
        update_fields = ["due_date"]
        installment.due_date = new_due
        if (
            installment.status in (InstallmentStatus.LATE, InstallmentStatus.FAILED)
            and new_due >= timezone.localdate()
            and not installment.is_settled
        ):
            installment.status = InstallmentStatus.SCHEDULED
            update_fields.append("status")
        installment.save(update_fields=update_fields)
        after = _installment_snapshot(installment)
        after["reason"] = serializer.validated_data.get("reason", "")
        audit = _audit(
            request.user,
            installment.plan.member,
            OpsAction.RESCHEDULE_DUE_DATE,
            before,
            after,
        )
        return Response({"installment": after, "audit_id": audit.id}, status=status.HTTP_200_OK)


class AdjustLimitView(SupportOnlyView):
    @transaction.atomic
    def post(self, request, pk):
        serializer = AdjustLimitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member = get_object_or_404(Member, pk=pk)
        new_limit = serializer.validated_data["limit_cents"]
        before = {
            "limit_cents": current_limit_cents(member),
            "available_cents": available_spending_power(member),
        }
        outstanding = outstanding_cents(member)
        limit = SpendingLimit.objects.create(
            member=member,
            limit_cents=new_limit,
            available_cents=max(new_limit - outstanding, 0),
            reason="MANUAL",
        )
        after = {
            "limit_cents": limit.limit_cents,
            "available_cents": limit.available_cents,
            "reason": serializer.validated_data.get("reason", ""),
        }
        audit = _audit(request.user, member, OpsAction.ADJUST_LIMIT, before, after)
        return Response(
            {
                "limit": {
                    "id": limit.id,
                    "limit_cents": limit.limit_cents,
                    "available_cents": limit.available_cents,
                    "reason": limit.reason,
                },
                "audit_id": audit.id,
            },
            status=status.HTTP_201_CREATED,
        )
