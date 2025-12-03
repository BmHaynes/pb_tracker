from pathlib import Path


def clan_members():
    here = Path(__file__).parent
    return open(f"{here}/../data/clan_members.txt").read().split(",")