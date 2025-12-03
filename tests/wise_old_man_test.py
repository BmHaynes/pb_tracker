from src import clan

def test_get_clan_members():
    result = clan.clan_members()
    assert "diyironfebtw" in result
