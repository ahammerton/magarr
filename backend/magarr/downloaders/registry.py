from __future__ import annotations

import httpx

from magarr.domain.enums import DownloadClientImplementation
from magarr.downloaders.base import ClientSettings, DownloadClient
from magarr.downloaders.deluge import DelugeClient
from magarr.downloaders.nzbget import NzbgetClient
from magarr.downloaders.qbittorrent import QbittorrentClient
from magarr.downloaders.rtorrent import RtorrentClient
from magarr.downloaders.sabnzbd import SabnzbdClient
from magarr.downloaders.transmission import TransmissionClient

IMPLEMENTATIONS: dict[DownloadClientImplementation, type[DownloadClient]] = {
    DownloadClientImplementation.SABNZBD: SabnzbdClient,
    DownloadClientImplementation.NZBGET: NzbgetClient,
    DownloadClientImplementation.QBITTORRENT: QbittorrentClient,
    DownloadClientImplementation.DELUGE: DelugeClient,
    DownloadClientImplementation.TRANSMISSION: TransmissionClient,
    DownloadClientImplementation.RTORRENT: RtorrentClient,
}


def settings_model(implementation: DownloadClientImplementation) -> type[ClientSettings]:
    return IMPLEMENTATIONS[implementation].settings_model


def build_client(
    implementation: DownloadClientImplementation, settings: dict, http: httpx.AsyncClient
) -> DownloadClient:
    cls = IMPLEMENTATIONS[implementation]
    return cls(cls.settings_model.model_validate(settings), http)
