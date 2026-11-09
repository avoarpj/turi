"""Persistent SDS cache owned by Turi; independent from the invocation directory."""
from apps.turi.src.config.projectsettings.settings import BASE_DIR as TURI_BASE_DIR

BASE_DIR = TURI_BASE_DIR / "downloads" / "sds_cache"
