"""GitOps-managed Seahub OAuth role hook; only trusted IdP claims are accepted."""


def custom_get_user_role(remote_role_value):
    if remote_role_value != "discord_10gb":
        raise ValueError("Unsupported OAuth role")
    from seahub_discord_quota import mark_discord_login
    mark_discord_login()
    # Keep native user permissions, without invoking Pro-only role quota RPCs.
    return "default"
