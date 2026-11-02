# Public DNS zone files

Edit the domain's BIND-format `.zone` file here, then commit and push. Argo CD's
nameserver PostSync job parses every file before reconciling the reviewed RRsets
through Technitium's API. There is no whole-zone import or deletion.

```dns
$ORIGIN pmh.so.
$TTL 300
_minecraft._tcp.hawal IN SRV 0 5 25565 play.pmh.codes.
```

- Supported record types: A, AAAA, CNAME, MX, SRV and TXT. Relative owners and
  targets, `@`, wildcards, comments, inherited owners, TTL units, multiline RDATA
  and escaped/multiple TXT strings use standard zone syntax. Absolute targets
  outside the zone **must end with a dot**.
- SOA/serial, NS, DNSSEC keys/signatures and certificate-validation TXT records
  remain server-managed. Do not copy them into these files. HTTPS/ECH and IPv4
  hints are generated from the Gateway A records and `configuration/ech.json`.
- Only `$ORIGIN` and `$TTL` directives are accepted. `$INCLUDE`, `$GENERATE`,
  out-of-zone owners and unsupported record types fail before DNS changes.
- `configuration/zones.json` holds zone policies, not records. Each allowed
  public zone in `configuration/dns01.json` needs a policy, a `.zone` file and
  a ConfigMap entry in `nameserver/kustomization.yml`.
- Existing safety rules still apply: new records can be added, but conflicting
  RRsets are not silently replaced. Removing a line does **not** delete live
  records. Address changes/deletions require a separately reviewed migration;
  this protects dynamic data and unexpected existing records.

The parser dependency is pinned by version and hash in
`images/nameserver/requirements.txt` and baked into the configuration-job image;
no packages are downloaded at runtime.

Local validation (use a virtual environment with that requirements file):

```sh
python -m unittest discover -s nameserver/configuration -p 'test_*.py'
python nameserver/configuration/zonefiles.py nameserver/configuration nameserver/zones
kubectl kustomize nameserver
```
