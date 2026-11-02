# Encrypted ClientHello

NGINX loads the existing X25519 ECH key from Vault via `gateway-ech-secrets`.
The private key is never stored in Git. `nameserver/configuration/ech.json`
contains only its public ECHConfigList, not a credential.

The nameserver PostSync hook publishes HTTPS ServiceMode records with `alpn`
and `ech` at every imported Gateway IPv4 owner, including existing wildcards.
It excludes external addresses (Minecraft `play`, mail CNAMEs, nameservers),
does not introduce new DNS nodes that could shadow wildcard addresses, and
refuses unexpected existing HTTPS records rather than replacing them.

Before publishing a replacement config, load its key on **every** Gateway,
verify TLS with ECH required and normal certificate validation, then update
the public list. Retain old keys through DNS TTL/cache overlap; do not rotate
the Vault key independently of DNS or claim that ordinary TLS proves ECH.

ECH support depends on the client's HTTPS DNS record resolution and TLS stack.
Clients without ECH retain ordinary HTTPS support.
