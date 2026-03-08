from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ChatViewSet

router = DefaultRouter()
router.register(r"conversations", ChatViewSet, basename="chat-conversation")

urlpatterns = [
    path("", include(router.urls)),
]
