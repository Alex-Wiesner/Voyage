from django.contrib.contenttypes.models import ContentType
from django.db.models import Max, Q
from rest_framework.exceptions import ValidationError

from adventures.models import (
    Checklist,
    Collection,
    CollectionItineraryDay,
    CollectionItineraryItem,
    Lodging,
    Location,
    Note,
    Transportation,
    Visit,
)
from adventures.permissions import IsOwnerOrSharedWithFullAccess
from adventures.serializers import (
    CollectionItineraryDaySerializer,
    CollectionItineraryItemSerializer,
    CollectionSerializer,
    UltraSlimCollectionSerializer,
)
from adventures.utils.itinerary import reorder_itinerary_items
from mcp_server import MCPToolset
from mcp_server.djangomcp import global_mcp_server


class VoyageTripTools(MCPToolset):
    mcp_server = global_mcp_server

    def _assert_authenticated(self):
        if (
            not getattr(self.request, "user", None)
            or not self.request.user.is_authenticated
        ):
            raise ValidationError("Authentication required")

    def _accessible_collections_queryset(self):
        self._assert_authenticated()
        user = self.request.user
        return Collection.objects.filter(Q(user=user) | Q(shared_with=user)).distinct()

    def list_collections(self):
        """List collections visible to authenticated user."""
        queryset = self._accessible_collections_queryset().order_by("-updated_at")
        return UltraSlimCollectionSerializer(
            queryset,
            many=True,
            context={"request": self.request},
        ).data

    def get_collection_details(self, collection_id: str):
        """Get collection details, itinerary items, and itinerary-day metadata."""
        try:
            collection = self._accessible_collections_queryset().get(id=collection_id)
        except Collection.DoesNotExist as exc:
            raise ValidationError("Collection not found or not accessible") from exc
        data = CollectionSerializer(collection, context={"request": self.request}).data
        itinerary_items = CollectionItineraryItem.objects.filter(collection=collection)
        itinerary_days = CollectionItineraryDay.objects.filter(collection=collection)
        data["itinerary"] = CollectionItineraryItemSerializer(
            itinerary_items, many=True
        ).data
        data["itinerary_days"] = CollectionItineraryDaySerializer(
            itinerary_days, many=True
        ).data
        return data

    def list_itinerary_items(self, collection_id: str | None = None):
        """List itinerary items; optionally limit by collection_id."""
        self._assert_authenticated()
        queryset = CollectionItineraryItem.objects.filter(
            Q(collection__user=self.request.user)
            | Q(collection__shared_with=self.request.user)
        ).distinct()

        if collection_id:
            queryset = queryset.filter(collection_id=collection_id)

        queryset = queryset.order_by("date", "order")
        return CollectionItineraryItemSerializer(queryset, many=True).data

    def create_itinerary_item(
        self,
        collection_id: str,
        content_type: str,
        object_id: str,
        date: str | None = None,
        is_global: bool = False,
        order: int | None = None,
    ):
        """Create a new itinerary item."""
        try:
            collection = self._accessible_collections_queryset().get(id=collection_id)
        except Collection.DoesNotExist as exc:
            raise ValidationError("Collection not found or not accessible") from exc

        content_map = {
            "location": Location,
            "transportation": Transportation,
            "note": Note,
            "lodging": Lodging,
            "visit": Visit,
            "checklist": Checklist,
        }
        model_class = content_map.get((content_type or "").lower())
        if not model_class:
            raise ValidationError("Invalid content_type")

        try:
            content_object = model_class.objects.get(id=object_id)
        except model_class.DoesNotExist as exc:
            raise ValidationError("Referenced object not found") from exc
        permission_checker = IsOwnerOrSharedWithFullAccess()
        if not permission_checker.has_object_permission(
            self.request, None, content_object
        ):
            raise ValidationError(
                "User does not have permission to access this content"
            )

        if is_global and date:
            raise ValidationError("Global itinerary items must not include a date")
        if (not is_global) and not date:
            raise ValidationError("Dated itinerary items must include a date")

        if order is None:
            if is_global:
                existing_max = (
                    CollectionItineraryItem.objects.filter(
                        collection=collection, is_global=True
                    )
                    .aggregate(max_order=Max("order"))
                    .get("max_order")
                )
            else:
                existing_max = (
                    CollectionItineraryItem.objects.filter(
                        collection=collection, date=date, is_global=False
                    )
                    .aggregate(max_order=Max("order"))
                    .get("max_order")
                )
            order = 0 if existing_max is None else int(existing_max) + 1

        itinerary_item = CollectionItineraryItem.objects.create(
            collection=collection,
            content_type=ContentType.objects.get_for_model(model_class),
            object_id=object_id,
            date=date,
            is_global=is_global,
            order=order,
        )
        return CollectionItineraryItemSerializer(itinerary_item).data

    def reorder_itinerary(self, items: list[dict]):
        """Bulk reorder itinerary items."""
        self._assert_authenticated()
        updated_items = reorder_itinerary_items(self.request.user, items or [])
        return CollectionItineraryItemSerializer(updated_items, many=True).data
