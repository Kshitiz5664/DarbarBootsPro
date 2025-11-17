# core/models_mixins.py
from decimal import Decimal
from django.db import models
from django.utils import timezone


class SoftDeleteManager(models.Manager):
    """Default manager returning only active records."""
    def get_queryset(self):
        return super().get_queryset().filter(is_active=True)


class AllObjectsManager(models.Manager):
    """Manager returning all records (including soft-deleted)."""
    def get_queryset(self):
        return super().get_queryset()


class SoftDeleteMixin(models.Model):
    """
    Soft delete mixin. Models inheriting this get:
    - is_active (boolean) to mark active/deleted
    - deleted_at timestamp
    - objects (active only) and all_objects (including deleted) managers
    """
    is_active = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):
        """Soft-delete: mark record inactive and timestamp it."""
        self.is_active = False
        self.deleted_at = timezone.now()
        # Use save(update_fields=...) for efficiency
        self.save(update_fields=["is_active", "deleted_at"])

    def hard_delete(self, using=None, keep_parents=False):
        """Permanently remove from DB."""
        super(SoftDeleteMixin, self).delete(using=using, keep_parents=keep_parents)

    def restore(self):
        """Restore a soft-deleted record."""
        self.is_active = True
        self.deleted_at = None
        self.save(update_fields=["is_active", "deleted_at"])
