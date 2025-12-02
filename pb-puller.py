import os
import re


def lookup_user_profile(username):
    type_pattern = re.compile(r"^rsprofile\.rsprofile\.(\w+)\.type=(.+)$")
    display_pattern = re.compile(r"^rsprofile\.rsprofile\.(\w+)\.displayName=(.+)$")
    user_home = os.path.expanduser("~")
    file_path = os.path.join(user_home, ".runelite", "profiles2", "$rsprofile--1.properties")

    profiles = {}
    types = {}
    display_names = {}

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

        for hash_id, type_val in types.items():
            if type_val == "STANDARD" and hash_id in display_names:
                profiles[display_names[hash_id]] = hash_id

        return profiles[username]


print(lookup_user_profile("IronDrag94"))