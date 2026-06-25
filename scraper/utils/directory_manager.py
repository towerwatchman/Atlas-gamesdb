import os

from scraper.types.eTypes import database
from scraper.config import config


def createDirectories(db_type=None):
    """Ensure the package output dir (and its backup subdir) exist.
    Paths come from config so they always match where packager writes."""
    base = config.package_dir()
    os.makedirs(base, exist_ok=True)
    os.makedirs(os.path.join(base, "backup"), exist_ok=True)
