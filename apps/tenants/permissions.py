TEAM_MANAGE_ROLES = {"owner", "admin"}
CUSTOMER_MANAGE_ROLES = {"owner", "admin", "manager", "staff"}


def membership_has_permission(membership, permission):
    if not membership or not membership.is_active:
        return False

    if permission == "team.manage":
        return membership.role in TEAM_MANAGE_ROLES
    if permission == "customers.view":
        return True
    if permission == "customers.manage":
        return membership.role in CUSTOMER_MANAGE_ROLES

    return False
