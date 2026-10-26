# Lunalight peer update

The operator explicitly requested a new AS218822-side key on 2026-10-26.
Only the local WireGuard private key was regenerated; its value stays in Vault
at `secret/as218822/as218822-router-wireguard`, field
`WG_LUNALIGHT_PRIVATE_KEY`. Prior Vault versions are retained.

Send the following **public** settings to the Lunalight operator:

```ini
[Peer]
PublicKey = dDP/yFErrKuWFr0bKPCCXw8eAtzikchlV7pP7F22vCQ=
Endpoint = 168.110.121.95:51822
```

Keep the existing PSK, AllowedIPs, and BIRD tunnel addressing unchanged:

- AS218822: `fd00:218:822:2014:23::/127`
- Lunalight: `fd00:218:822:2014:23::1`
- Lunalight public key: `CJ9uENAlEiAN83abDU59qBT+oEmWxi5ZlwZRZ4HGjUk=`

Vault and the running gateway have the new local identity. The static remote
peer is installed now; at verification its latest-handshake timestamp was 0.
Confirm a nonzero handshake and Established BGP after the remote operator
updates the key. Never publish the private key or PSK.
