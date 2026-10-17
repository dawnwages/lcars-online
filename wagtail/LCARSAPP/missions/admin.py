from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html

from .models import Gate, Mission, MissionEvent, Snapshot


class ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class MissionEventInline(ReadOnlyInline):
    model = MissionEvent
    fields = ("seq", "station", "kind", "title", "rationale", "duration_ms", "model_name")
    readonly_fields = fields
    ordering = ("seq",)
    show_change_link = True


class GateInline(ReadOnlyInline):
    model = Gate
    fields = ("name", "status", "decided_via", "decided_by", "decided_at", "note")
    readonly_fields = fields


@admin.register(Mission)
class MissionAdmin(admin.ModelAdmin):
    list_display = ("id", "stardate", "kind", "status_badge", "verdict", "model_name",
                    "pending_gates", "created_at", "duration")
    list_filter = ("kind", "status", "model_name")
    search_fields = ("question", "verdict")
    readonly_fields = ("stardate", "question", "kind", "status", "model_name", "snapshot", "snapshot_sha256",
                       "seed", "prefect_flow_run_id", "code_version", "plan", "result", "review",
                       "verdict", "report_page", "created_at", "started_at", "finished_at")
    fields = readonly_fields[:4] + ("recording_url",) + readonly_fields[4:]
    inlines = [GateInline, MissionEventInline]

    def has_add_permission(self, request):
        return False  # Missions are started by the crew, not typed in

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {"complete": "#2e7d32", "failed": "#c62828", "rejected": "#c62828",
                  "awaiting_approval": "#ef6c00", "running": "#1565c0"}
        return format_html('<b style="color:{}">{}</b>', colors.get(obj.status, "#555"),
                           obj.get_status_display())

    @admin.display(description="Pending gates")
    def pending_gates(self, obj):
        return obj.gates.filter(status=Gate.Status.PENDING).count() or ""


@admin.register(MissionEvent)
class MissionEventAdmin(admin.ModelAdmin):
    list_display = ("mission", "seq", "station", "kind", "title", "duration_ms")
    list_filter = ("station", "kind", "mission")
    search_fields = ("title", "rationale")

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Gate)
class GateAdmin(admin.ModelAdmin):
    list_display = ("mission", "name", "status", "requested_at", "decided_via", "decided_by")
    list_filter = ("status", "name")
    readonly_fields = ("mission", "name", "status", "requested_at", "decided_at", "decided_by",
                       "decided_via")
    fields = readonly_fields + ("note",)
    actions = ["approve", "reject"]

    def has_add_permission(self, request):
        return False

    def _decide(self, request, queryset, status):
        pending = queryset.filter(status=Gate.Status.PENDING)
        count = pending.update(status=status, decided_at=timezone.now(),
                               decided_by=request.user, decided_via="admin")
        self.message_user(request, f"{count} gate(s) {status}.", messages.SUCCESS)

    @admin.action(description="Approve selected gates (make it so)")
    def approve(self, request, queryset):
        self._decide(request, queryset, Gate.Status.APPROVED)

    @admin.action(description="Reject selected gates")
    def reject(self, request, queryset):
        self._decide(request, queryset, Gate.Status.REJECTED)


@admin.register(Snapshot)
class SnapshotAdmin(admin.ModelAdmin):
    """Archive fetches, made by the scheduled Prefect flow. Read-only."""
    list_display = ("fetched_at", "status", "rows", "added", "removed", "revised", "short_sha")
    list_filter = ("status",)

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="New")
    def added(self, obj):
        return (obj.changes or {}).get("added", "")

    @admin.display(description="Removed")
    def removed(self, obj):
        return (obj.changes or {}).get("removed", "")

    @admin.display(description="Revised")
    def revised(self, obj):
        return (obj.changes or {}).get("revised", "")

    @admin.display(description="SHA-256")
    def short_sha(self, obj):
        return obj.sha256[:12]
