#!/bin/sh
# Never start routing, contact peers, or print decrypted environment values.
set -eu
umask 077
export BIRD_VALIDATE=1
if ! dotenvx run --quiet -f /etc/bird/.env -- sh -ec '
    missing=0
    for template in /etc/bird/peers/*.conf /etc/tunnels/wireguard/*.conf /etc/tunnels/gre/*.conf /etc/tunnels/zerotier/*.conf; do
        [ -f "$template" ] || continue
        for variable in $(envsubst --variables "$(cat "$template")"); do
            if ! printenv "$variable" >/dev/null; then
                printf "MISSING_VARIABLE %s\n" "$variable"
                missing=1
            fi
        done
    done
    [ "$missing" = 0 ] || exit 2
    render-bird-config
' > /run/bird/validation.log 2>&1; then
    # Native logs can include decrypted settings: expose only safe field names.
    grep -E '^MISSING_VARIABLE [A-Z0-9_]+$' /run/bird/validation.log | sort -u || true
    echo 'VALIDATION_FAILED: native logs retained only in temporary Pod memory'
    exit 1
fi
for config in /run/bird/wireguard/*.conf; do
    [ -f "$config" ] || continue
    own_public=$(sed -n 's/^PrivateKey[[:space:]]*=[[:space:]]*//p' "$config" | wg pubkey)
    sed -n 's/^PublicKey[[:space:]]*=[[:space:]]*//p' "$config" |
        while IFS= read -r peer_public; do
            if [ "$own_public" = "$peer_public" ]; then
                printf 'SELF_PEER %s: local and remote public keys are identical\n' "$(basename "$config")"
                exit 1
            fi
        done
done
echo 'PASS: original dotenv/templates and BIRD syntax; no peer/routing activation'
