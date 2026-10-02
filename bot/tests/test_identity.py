import pytest

from deskify_bot.deskify_client import ApiError
from deskify_bot.identity import EXPIRY_MARGIN_S, Identity


def test_unmapped_user_is_the_default(settings, client):
    assert Identity(settings, client).email_for("aad-anyone", "29:x") == "priya@northwind.example"


def test_mapped_by_aad_object_id_or_teams_id(settings, client):
    ident = Identity(settings, client)
    assert ident.email_for("aad-dana", None) == "dana@northwind.example"
    assert ident.email_for(None, "aad-dana") == "dana@northwind.example"


async def test_token_is_cached_until_shortly_before_expiry(settings, client, api):
    now = [0.0]
    ident = Identity(settings, client, clock=lambda: now[0])

    first = await ident.token_for(None, None)
    assert await ident.token_for(None, None) == first
    assert len(api.sign_ins) == 1

    now[0] = 600 - EXPIRY_MARGIN_S + 1
    await ident.token_for(None, None)
    assert len(api.sign_ins) == 2


async def test_two_users_get_two_tokens(settings, client):
    ident = Identity(settings, client)
    assert await ident.token_for("aad-dana", None) != await ident.token_for(None, None)


async def test_unknown_email_surfaces_as_api_error(settings, client):
    settings.user_map["aad-stranger"] = "someone@elsewhere.example"
    with pytest.raises(ApiError) as e:
        await Identity(settings, client).token_for("aad-stranger", None)
    assert e.value.status == 400
