"""Fetch new data from the NASA Exoplanet Archive on a schedule, with Prefect.

    uv run python manage.py ingest_archive        # fetch once, now
    uv run python manage.py serve_ingest          # run on a schedule (daily by default)

Each fetch becomes a Snapshot (visible in the admin) with its hash, row count
and what changed since the previous snapshot. Missions analyze the newest one.
"""
import datetime
import hashlib
import io
import os
import urllib.parse
import urllib.request

import django
from django.apps import apps

if not apps.ready:  # Prefect runs scheduled flows in a fresh process
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "LCARSAPP.settings.dev")
    django.setup()

import numpy as np
import pandas as pd
from django.utils import timezone
from prefect import flow, get_run_logger, task
from prefect.runtime import flow_run

from crew import science
from missions.models import Snapshot

TAP_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
COLUMNS = [
    "pl_name", "hostname", "disc_method", "disc_year", "disc_facility", "pl_orbper", "pl_rade",
    "pl_radeerr1", "pl_radeerr2", "pl_bmasse", "pl_bmasseerr1", "pl_bmasseerr2", "pl_bmassprov",
    "pl_eqt", "pl_insol", "st_teff", "st_rad", "st_mass", "sy_dist", "sy_pnum",
]
# A revision to any of these counts as a changed planet
TRACKED = ["disc_method", "pl_orbper", "pl_rade", "pl_radeerr1", "pl_bmasse", "pl_bmassprov", "st_teff"]
MIN_ROWS = 5000  # the archive has 6,000+ confirmed planets; far fewer means a bad download
SNAPSHOT_DIR = science.DATA_DIR / "snapshots"


def ensure_baseline():
    """Record the pinned October 7 snapshot so there is always something to compare with."""
    baseline, _ = Snapshot.objects.get_or_create(
        sha256=science.SNAPSHOT_SHA256,
        defaults={"fetched_at": timezone.make_aware(datetime.datetime(2026, 10, 7, 21, 0)),
                  "status": Snapshot.Status.OK, "path": science.SNAPSHOT.name, "rows": 6375,
                  "changes": {"baseline": True}})
    return baseline


@task(retries=3, retry_delay_seconds=30)
def fetch_archive() -> bytes:
    query = f"select {','.join(COLUMNS)} from pscomppars order by pl_name"
    url = f"{TAP_URL}?{urllib.parse.urlencode({'query': query, 'format': 'csv'})}"
    with urllib.request.urlopen(url, timeout=120) as resp:
        return resp.read()


@task
def validate(raw: bytes) -> pd.DataFrame:
    """Refuse anything that isn't a complete, well-formed planet table."""
    if raw.lstrip().startswith(b"<"):
        raise ValueError("Archive returned an error page, not CSV: " + raw[:300].decode(errors="replace"))
    df = pd.read_csv(io.BytesIO(raw))
    if list(df.columns) != COLUMNS:
        raise ValueError(f"Unexpected columns: {list(df.columns)}")
    if len(df) < MIN_ROWS:
        raise ValueError(f"Only {len(df)} rows; expected at least {MIN_ROWS}")
    if df["pl_name"].duplicated().any():
        raise ValueError("Duplicate planet names")
    return df


def _same(a, b):
    if pd.isna(a) and pd.isna(b):
        return True
    if isinstance(a, (int, float, np.number)) and isinstance(b, (int, float, np.number)):
        return bool(np.isclose(a, b, rtol=1e-9, atol=0))
    return a == b


@task
def compare(new: pd.DataFrame, old: pd.DataFrame, examples: int = 25) -> dict:
    new_i, old_i = new.set_index("pl_name"), old.set_index("pl_name")
    added = sorted(set(new_i.index) - set(old_i.index))
    removed = sorted(set(old_i.index) - set(new_i.index))
    revised = []
    for name in sorted(set(new_i.index) & set(old_i.index)):
        fields = {c: [old_i.at[name, c], new_i.at[name, c]] for c in TRACKED
                  if not _same(old_i.at[name, c], new_i.at[name, c])}
        if fields:
            revised.append({"pl_name": name, "fields": {k: [None if pd.isna(v) else v for v in vals]
                                                         for k, vals in fields.items()}})
    added_rows = new_i.loc[added, ["disc_method", "disc_year", "pl_rade", "pl_orbper"]]
    return {
        "added": len(added), "removed": len(removed), "revised": len(revised),
        "added_by_method": added_rows["disc_method"].value_counts().to_dict(),
        "added_examples": [{"pl_name": n, **{k: (None if pd.isna(v) else v) for k, v in r.items()}}
                           for n, r in added_rows.head(examples).iterrows()],
        "removed_examples": removed[:examples],
        "revised_examples": revised[:examples],
    }


@flow(name="archive-ingest", log_prints=True)
def archive_ingest() -> int:
    """Fetch, validate, store and diff one snapshot. Returns the Snapshot id."""
    logger = get_run_logger()
    previous = Snapshot.latest_usable() or ensure_baseline()
    run_id = str(flow_run.id or "")
    try:
        raw = fetch_archive()
        df = validate(raw)
    except Exception as exc:
        snap = Snapshot.objects.create(status=Snapshot.Status.FAILED, error=str(exc)[:2000],
                                       previous=previous, prefect_flow_run_id=run_id)
        logger.error("Archive fetch failed: %s", exc)
        raise

    sha = hashlib.sha256(raw).hexdigest()
    if sha == previous.sha256:
        snap = Snapshot.objects.create(
            status=Snapshot.Status.UNCHANGED, path=previous.path, sha256=sha, rows=len(df),
            previous=previous, changes={"added": 0, "removed": 0, "revised": 0},
            prefect_flow_run_id=run_id)
        logger.info("No change since %s", previous.fetched_at)
        return snap.pk

    old_df, _ = science.load_snapshot(previous.path, previous.sha256)
    changes = compare(df, old_df[COLUMNS])
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    name = f"pscomppars-{timezone.now():%Y%m%dT%H%M%SZ}.csv"
    (SNAPSHOT_DIR / name).write_bytes(raw)
    snap = Snapshot.objects.create(
        status=Snapshot.Status.OK, path=f"snapshots/{name}", sha256=sha, rows=len(df),
        previous=previous, changes=changes, prefect_flow_run_id=run_id)
    logger.info("Saved %s: %d planets, +%d new, -%d removed, %d revised",
                name, len(df), changes["added"], changes["removed"], changes["revised"])
    return snap.pk
