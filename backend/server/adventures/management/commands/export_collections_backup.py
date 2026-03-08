import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

from adventures.models import Collection, CollectionItineraryItem


class Command(BaseCommand):
    help = (
        "Export Collection and CollectionItineraryItem data to a JSON backup "
        "file before upgrades/migrations."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            type=str,
            help="Optional output file path (default: ./collections_backup_<timestamp>.json)",
        )

    def handle(self, *args, **options):
        backup_timestamp = timezone.now()
        timestamp = backup_timestamp.strftime("%Y%m%d_%H%M%S")
        output_path = Path(
            options.get("output") or f"collections_backup_{timestamp}.json"
        )

        if output_path.parent and not output_path.parent.exists():
            raise CommandError(f"Output directory does not exist: {output_path.parent}")

        collections = list(
            Collection.objects.values(
                "id",
                "user_id",
                "name",
                "description",
                "is_public",
                "is_archived",
                "start_date",
                "end_date",
                "link",
                "primary_image_id",
                "created_at",
                "updated_at",
            )
        )

        shared_with_map = {
            str(collection.id): list(
                collection.shared_with.values_list("id", flat=True)
            )
            for collection in Collection.objects.prefetch_related("shared_with")
        }
        for collection in collections:
            collection["shared_with_ids"] = shared_with_map.get(
                str(collection["id"]), []
            )

        itinerary_items = list(
            CollectionItineraryItem.objects.select_related("content_type").values(
                "id",
                "collection_id",
                "content_type_id",
                "content_type__app_label",
                "content_type__model",
                "object_id",
                "date",
                "is_global",
                "order",
                "created_at",
            )
        )

        backup_payload = {
            "backup_type": "collections_snapshot",
            "timestamp": backup_timestamp.isoformat(),
            "counts": {
                "collections": len(collections),
                "collection_itinerary_items": len(itinerary_items),
            },
            "collections": collections,
            "collection_itinerary_items": itinerary_items,
        }

        try:
            with output_path.open("w", encoding="utf-8") as backup_file:
                json.dump(backup_payload, backup_file, indent=2, cls=DjangoJSONEncoder)
        except OSError as exc:
            raise CommandError(f"Failed to write backup file: {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise CommandError(f"Failed to serialize backup data: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                "Exported collections backup to "
                f"{output_path} "
                f"at {backup_timestamp.isoformat()} "
                f"(collections: {len(collections)}, "
                f"itinerary_items: {len(itinerary_items)})."
            )
        )
