TEAM_MANAGE_ROLES = {"owner", "admin"}


def membership_has_permission(membership, permission):
    if not membership or not membership.is_active:
        return False

    if permission == "team.manage":
        return membership.role in TEAM_MANAGE_ROLES

    return False
