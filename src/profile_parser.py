import re
from collections import defaultdict

type_pattern = re.compile(r"^rsprofile\.rsprofile\.(\w+)\.type=(.+)$")
display_pattern = re.compile(r"^rsprofile\.rsprofile\.(\w+)\.displayName=(.+)$")

def _parse_pb(line: str):
    try:
        key, pb = line.split("=", 1)
        parts = key.split(".")
        hash_val = parts[2]
        name = ".".join(parts[3:]).replace("\\ ", " ")
        return hash_val, name, float(pb)
    except ValueError:
        return None, None, None

def parse_profile(file_path: str, game_mode: str = "STANDARD"):
    profiles = {}
    types = {}
    display_names = {}
    personal_bests = defaultdict(lambda: defaultdict(float))

    with open(file_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            m_type = type_pattern.match(line)
            if m_type:
                hash_id, type_val = m_type.groups()
                types[hash_id] = type_val
                continue

            m_disp = display_pattern.match(line)
            if m_disp:
                hash_id, disp_val = m_disp.groups()
                display_names[hash_id] = disp_val
                continue

            if line.startswith("personalbest.rsprofile"):
                hash, name, pb = _parse_pb(line)
                if hash:
                    personal_bests[hash][name] = pb

        for hash_id, type_val in types.items():
            if type_val == game_mode and hash_id in display_names:
                profiles[display_names[hash_id]] = personal_bests[hash_id]

        return profiles