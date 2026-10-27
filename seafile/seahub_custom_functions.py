"""GitOps-managed Seahub OAuth role hook; only trusted IdP claims are accepted."""


def custom_get_user_role(remote_role_value):
    if remote_role_value != "discord_10gb":
        raise ValueError("Unsupported OAuth role")
    return "discord_10gb"
