# AS218822 startup checks

The user approved retaining the existing encrypted dotenv configuration and
its existing key. `as218822/bird-dotenvx` in Vault supplies `DOTENV_PRIVATE_KEY`.
Do not rotate/import/rewrite external peer identities automatically. The
previously generated router keys remain unused until their public keys match
the corresponding peer configuration.

`validate-existing.sh` runs inside the pinned original routing image with
`BIRD_VALIDATE=1`, a memory-backed `/run/bird`, no network capabilities, no
service-account token, and a deny-all ingress/egress NetworkPolicy. Mount it
read-only and supply the relevant existing Secret fields as environment
variables. It checks all required template fields before running the native
renderer, because the renderer's validation mode otherwise substitutes dummy
values for missing fields. Raw decrypted configuration/logs must never be
printed or copied out of the temporary Pod.

Current validation: core dotenv/templates and BIRD syntax pass with the
prepared internal `WG_CORE_PRIVATE_KEY`. This does not start BGP, establish a
tunnel, prove connectivity, or validate the peer's matching public key.
The GRE image additionally requires `WG_LUNALIGHT_PRIVATE_KEY` and
`WG_LUNALIGHT_PRESHARED_KEY`. The prepared Lunalight private key is new/unused;
the real PSK is absent. Obtain existing matching credentials or explicit peer
acceptance before activation; do not invent a PSK or silently disable the peer.

The production manifests still contain privileged containers and host-network
GRE and must not be applied as a whole. Complete the non-privileged networking
changes and internal public-key matching before registering the Application.
