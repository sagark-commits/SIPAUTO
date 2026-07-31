"""Provider templates."""

from sipauto.models import Inventory, Provider
from sipauto.providers.airtel import AirtelProvider
from sipauto.providers.base import ProviderTemplate
from sipauto.providers.jio import JioProvider
from sipauto.providers.tata import TataProvider
from sipauto.providers.vodafone import VodafoneProvider

_REGISTRY: dict[Provider, ProviderTemplate] = {
    Provider.TATA: TataProvider(),
    Provider.JIO: JioProvider(),
    Provider.AIRTEL: AirtelProvider(),
    Provider.VODAFONE: VodafoneProvider(),
}


def get_provider(inv: Inventory) -> ProviderTemplate:
    try:
        return _REGISTRY[inv.provider]
    except KeyError as exc:
        raise ValueError(f"Unsupported provider: {inv.provider}") from exc


__all__ = ["get_provider", "ProviderTemplate"]
