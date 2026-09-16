"""Atlas Cloud is reachable through the unified gateway, not a bespoke adapter."""

import pytest

from src.api.schemas.api_key import APIKeyCreate
from src.models.api_key import APIKeyProvider
from src.services.provider.registry import PROVIDERS, connection


def test_atlascloud_is_a_registered_provider_preset():
    assert "atlascloud" in PROVIDERS
    label, base_url = PROVIDERS["atlascloud"]
    assert label == "Atlas Cloud"
    assert base_url == "https://api.atlascloud.ai/v1"
    # The /api-keys/provider-presets endpoint serves PROVIDERS verbatim, so the
    # registry entry is what puts Atlas Cloud in the UI's provider list.


def test_atlascloud_connection_resolves_to_the_openai_compatible_endpoint():
    for base_url in (None, "https://api.atlascloud.ai/v1"):
        conn = connection("atlascloud", base_url)
        assert conn["provider"] == "atlascloud"
        assert conn["base_url"] == "https://api.atlascloud.ai/v1"
        assert conn["root_url"] == "https://api.atlascloud.ai"


def test_atlascloud_connection_still_rejects_unsafe_base_urls():
    for bad in ("http://user:pw@api.atlascloud.ai/v1", "ftp://api.atlascloud.ai/v1",
                "https://api.atlascloud.ai/v1?token=x"):
        with pytest.raises(ValueError):
            connection("atlascloud", bad)


def test_atlascloud_is_accepted_by_the_api_key_schema_and_enum():
    assert APIKeyProvider.ATLASCLOUD.value == "atlascloud"
    assert APIKeyCreate.validate_provider("AtlasCloud") == "atlascloud"
