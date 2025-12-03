from pathlib import Path
from src import profile_parser

here = Path(__file__).parent
property_file_path = f"{here}/rsc/$rsprofile--1.properties"

def test_profile_parser():
    profiles = profile_parser.parse_profile(property_file_path)
    assert len(profiles) == 6
    assert profiles["DIYIronFeBTW"]["alchemical hydra"] == 77.0
    assert profiles["car go space"]["zulrah"] == 72.0

def test_profile_parser_alternate_game_mode():
    profiles = profile_parser.parse_profile(property_file_path, "GRID_MASTER")
    assert len(profiles) == 2
    assert profiles["DIYIronFeBTW"]["nex"] == 180.0
    assert profiles["DIYIronFeBTW"]["araxxor"] == 16.0

def test_profile_parse_pb():
    name_hash = "IMQq29Nm"
    name = "araxxor"
    pb = 123.4
    rname_hash, rname, rpb = profile_parser._parse_pb(f"personalbest.rsprofile.{name_hash}.{name}={pb}")

    assert rname_hash == name_hash
    assert rname == name
    assert rpb == pb


def test_profile_parse_pb_invalid():
    rhash, _, _ = profile_parser._parse_pb(f"invalid string")
    assert rhash is None
