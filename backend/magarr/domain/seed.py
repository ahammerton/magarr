from sqlalchemy.orm import Session

from magarr.domain.download_clients import get_download_settings
from magarr.domain.media_settings import get_media_settings
from magarr.domain.naming_config import ensure_naming_config
from magarr.domain.profiles import ensure_default_profile


def seed_defaults(session: Session) -> None:
    """Idempotent first-run data: default quality profile, naming scheme, download settings."""
    ensure_default_profile(session)
    ensure_naming_config(session)
    get_download_settings(session)
    get_media_settings(session)
    session.commit()
