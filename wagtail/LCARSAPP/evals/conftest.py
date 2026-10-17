"""Evals grade recorded missions in the project database (not a test database)."""
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "LCARSAPP.settings.dev")
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
os.environ.setdefault("DEEPTEAM_TELEMETRY_OPT_OUT", "YES")
django.setup()
