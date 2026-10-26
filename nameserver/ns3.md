# Third nameserver

- `ns3.pmh.codes` / `168.107.39.218` runs on `pmhoci3` (`10.2.0.10`).
- `nameserver-tertiary` has its own node-local PVC and cert-manager certificate.
- It joins the existing native Technitium cluster as a Secondary. The Primary
  remains `ns2.pmh.codes`; existing volumes and DNSSEC signing keys stay in place.
- The cluster catalog provisions the existing zones automatically. Do not copy
  the Primary's `/etc/dns` directory or initialize another Primary cluster.
- For initial joining, use `admin/cluster/initJoin` on the new server with
  `secondaryNodeIpAddresses=168.107.39.218`,
  `primaryNodeUrl=https://ns2.pmh.codes:53443/`,
  `primaryNodeIpAddress=10.1.0.102`, and `ignoreCertificateErrors=false`.
  Supply the existing administrator credentials from the Kubernetes Secret in
  memory only; do not put passwords or session tokens in arguments, Git or logs.
  The container trusts only the public certificate from `nameserver-tls-secret`
  through `SSL_CERT_FILE`; the Primary's private key is not mounted.
- Joining is a one-time bootstrap operation on the new, empty instance. On
  subsequent deploys, retain the PVC and verify membership instead of rejoining.
- Authoritative NS/A records are GitOps-managed. Registrar/parent-zone delegation
  is separate: add `ns3.pmh.codes` and its glue IP where appropriate. Existing
  delegation and DS records are not automatically replaced.
