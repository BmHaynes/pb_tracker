import requests

BASE_URL = "https://api.wiseoldman.net/v2"

def download_clan_members(clan_name: str):
    search_url = f"{BASE_URL}/groups"
    resp = requests.get(search_url, params={"name": clan_name})
    resp.raise_for_status()
    groups = resp.json()

    if not groups:
        raise ValueError(f"No clan found with name '{clan_name}'")

    group_id = groups[0]["id"]
    group_url = f"{BASE_URL}/groups/{group_id}"
    group_resp = requests.get(group_url)
    group_resp.raise_for_status()
    group_data = group_resp.json()

    members = [m["player"]["username"] for m in group_data.get("memberships", [])]
    return members


if __name__ == "__main__":
    members = download_clan_members("Conviction")
    open("../data/clan_members.txt", "w").write(",".join(members))