from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.serializers import MemberMeSerializer


class MemberMeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        member = getattr(request.user, "member", None)
        if member is None:
            return Response({"detail": "No member profile for this user."}, status=404)
        return Response(MemberMeSerializer(member).data)
