from django.conf import settings
from django.db import models
from django.utils import timezone


class Snapshot(models.Model):
    """One fetch of the NASA Exoplanet Archive. Missions analyze a recorded snapshot."""

    class Status(models.TextChoices):
        OK = "ok", "Saved"
        UNCHANGED = "unchanged", "Unchanged since last fetch"
        FAILED = "failed", "Failed"

    fetched_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=16, choices=Status.choices)
    path = models.CharField(max_length=500, blank=True, help_text="CSV file, relative to crew/data")
    sha256 = models.CharField(max_length=64, blank=True)
    rows = models.PositiveIntegerField(null=True, blank=True)
    previous = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="+")
    changes = models.JSONField(null=True, blank=True,
                               help_text="Planets added, removed and revised since the previous snapshot")
    error = models.TextField(blank=True)
    prefect_flow_run_id = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-fetched_at"]
        get_latest_by = "fetched_at"

    def __str__(self):
        return f"{self.fetched_at:%Y-%m-%d %H:%M} · {self.rows or 0} planets · {self.get_status_display()}"

    def content_source(self):
        """The snapshot that introduced this data (an unchanged re-check points back to it)."""
        snap = self
        while snap.status == self.Status.UNCHANGED and snap.previous_id:
            snap = snap.previous
        return snap

    @classmethod
    def latest_usable(cls):
        return cls.objects.filter(status__in=[cls.Status.OK, cls.Status.UNCHANGED]).first()


class Mission(models.Model):
    """One run of the crew against a question. Every run is kept."""

    class Kind(models.TextChoices):
        ANALYSIS = "analysis", "Analysis"
        NEGATIVE_CONTROL = "negative_control", "Negative control"
        EVAL = "eval", "Eval"
        RED_TEAM = "red_team", "Red team"

    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        AWAITING_APPROVAL = "awaiting_approval", "Awaiting approval"
        RUNNING = "running", "Running"
        COMPLETE = "complete", "Complete"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"

    stardate = models.CharField(max_length=32, editable=False)
    question = models.TextField()
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.ANALYSIS)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PLANNED)

    # Reproducibility: everything needed to rerun this mission
    model_name = models.CharField(max_length=200, blank=True)
    snapshot_sha256 = models.CharField(max_length=64, blank=True)
    snapshot = models.ForeignKey(Snapshot, null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="missions")
    seed = models.IntegerField(default=0)
    prefect_flow_run_id = models.CharField(max_length=64, blank=True)
    code_version = models.CharField(max_length=64, blank=True, help_text="git commit")

    plan = models.JSONField(null=True, blank=True)
    result = models.JSONField(null=True, blank=True)
    review = models.JSONField(null=True, blank=True)
    verdict = models.CharField(max_length=200, blank=True)
    report_page = models.ForeignKey(
        "wagtailcore.Page", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    recording_url = models.URLField(blank=True, help_text="Screen recording of this mission")

    created_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.stardate:
            # Kelvin-timeline style stardate: year.day-of-year
            now = timezone.localtime()
            self.stardate = f"{now.year}.{now.timetuple().tm_yday:03d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Mission {self.pk} · stardate {self.stardate}"

    @property
    def duration(self):
        if self.started_at and self.finished_at:
            return self.finished_at - self.started_at


class MissionEvent(models.Model):
    """Append-only log of everything that happened during a mission."""

    class Station(models.TextChoices):
        OPS = "ops", "Ops"
        SCIENCE = "science", "Science Officer"
        ENGINEERING = "engineering", "Engineering"
        TACTICAL = "tactical", "Tactical"
        LOG = "log", "Captain's Log"
        CAPTAIN = "captain", "Captain"
        SYSTEM = "system", "System"

    class Kind(models.TextChoices):
        DECISION = "decision", "Decision"
        TOOL_CALL = "tool_call", "Tool call"
        TOOL_RESULT = "tool_result", "Tool result"
        MODEL_OUTPUT = "model_output", "Model output"
        GATE = "gate", "Approval gate"
        NOTE = "note", "Note"
        ERROR = "error", "Error"

    mission = models.ForeignKey(Mission, on_delete=models.CASCADE, related_name="events")
    seq = models.PositiveIntegerField()
    station = models.CharField(max_length=16, choices=Station.choices)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    title = models.CharField(max_length=300)
    rationale = models.TextField(blank=True)
    alternatives = models.JSONField(default=list, blank=True)
    payload = models.JSONField(null=True, blank=True)
    model_name = models.CharField(max_length=200, blank=True)
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["mission", "seq"]
        constraints = [models.UniqueConstraint(fields=["mission", "seq"], name="unique_event_seq")]

    def __str__(self):
        return f"{self.seq:03d} {self.get_station_display()}: {self.title}"


class Gate(models.Model):
    """A point where the mission waits for a person. Enforced in code, not prompts."""

    class Name(models.TextChoices):
        DATA_CARD = "data_card", "Approve data card and population"
        PLAN = "plan", "Approve analysis plan"
        PLAN_REVISION = "plan_revision", "Approve revised analysis plan"
        PUBLISH = "publish", "Publish Captain's Log"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    mission = models.ForeignKey(Mission, on_delete=models.CASCADE, related_name="gates")
    name = models.CharField(max_length=16, choices=Name.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    requested_at = models.DateTimeField(default=timezone.now)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    decided_via = models.CharField(
        max_length=100, blank=True,
        help_text="How the decision was made, e.g. 'admin' or 'pre-approved for recording'")
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["mission", "requested_at"]
        constraints = [models.UniqueConstraint(fields=["mission", "name"], name="unique_gate")]

    def __str__(self):
        return f"{self.get_name_display()} ({self.status})"
