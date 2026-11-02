# Public domain and IP TLS

`certificate.yml` is the single edge Certificate, mounted directly by NGINX
as `gateway-tls-secret`. No Kustomize patch disables it or changes its mount.
Its DNS SANs preserve the public wildcard domains; IP SANs cover the current
three public Gateway IPv4 addresses. Do not restore the retired IP addresses.

The original `letsencrypt` ClusterIssuer uses the required `shortlived` profile.
Domains use Technitium DNS-01, including not.ai.kr; IPs use the native Gateway
HTTP-01 solver. Port 80 forwards **only** `/.well-known/acme-challenge/` to
Envoy's temporary solver HTTPRoutes. Other HTTP requests still redirect to TLS.
cert-manager self-checks HTTP reachability before accepting authorization.

IP certificates expire after roughly 160 hours. cert-manager renews 48 hours
before expiry. The existing global Reloader watches the mounted Secret and
rolls the three NGINX pods sequentially when it changes. Inspect Certificate
Ready, renewalTime, and the actual served certificate; do not treat an ACME
account Ready condition as successful issuance.

For first deployment, make the HTTP path available and let all edge pods become
Ready before requesting IP authorization. When replacing a working certificate,
validate its public chain and all SANs before changing the mount. A rollout of
a host-networked listener briefly interrupts that node, so avoid concurrent
IP validation/edge rollout when possible. Existing key and ECH handling remain
separate; changing a TLS certificate must not rotate the ECH key.
