path "secret/data/authentik/authentik-secrets" {
  capabilities = ["read"]
}

path "secret/data/authentik/bootstrap-worker" {
  capabilities = ["read"]
}

path "secret/data/authentik/discord-oauth" {
  capabilities = ["read"]
}
