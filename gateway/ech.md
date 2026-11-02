# Encrypted ClientHello

NGINX loads the existing X25519 ECH key from Vault via `gateway-ech-secrets`.
The private key is never stored in Git. `nameserver/configuration/ech.json`
contains only its public ECHConfigList, not a credential.

The nameserver PostSync hook publishes HTTPS ServiceMode records with `alpn`,
`ech`, and explicit `ipv4hint` values matching each owner's A records in
`nameserver/zones/*.zone` at every Gateway IPv4 owner, including existing wildcards.
It excludes external addresses (Minecraft `play`, mail CNAMEs, nameservers),
does not introduce new DNS nodes that could shadow wildcard addresses, and
refuses unexpected existing HTTPS records rather than replacing them. Existing
records matching exactly except for a missing `ipv4hint` are updated in place;
automatic hints remain disabled so only reviewed addresses are advertised.
Technitium's API encodes ECH as hex octets; the reconciler converts those
losslessly to/from the standard public base64 ECHConfigList.

Before publishing a replacement config, load its key on **every** Gateway,
verify TLS with ECH required and normal certificate validation, then update
the public list. Retain old keys through DNS TTL/cache overlap; do not rotate
the Vault key independently of DNS or claim that ordinary TLS proves ECH.

ECH support depends on the client's HTTPS DNS record resolution and TLS stack.
Clients without ECH retain ordinary HTTPS support.
