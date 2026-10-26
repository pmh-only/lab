# Welplan notice

`index.html` is published to the RustFS `welplan` bucket with anonymous object
reads, like the other bucket-hosted sites. The existing `*.pmh.codes` bucket
route serves it at `https://welplan.pmh.codes/`; no dedicated HTTPRoute,
Application, workload, database, or identity is needed. Keep this domain's
existing analytics opt-out. Welplan's former application remains retired.
