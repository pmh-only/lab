# PMH Identity

Minimal dark branding for Authentik's native login and application portal.
No replacement login UI, third-party fonts, scripts or authentication changes.
Native errors, MFA, language selection and keyboard focus remain available.

The brand is stored by Authentik's native API, not in a replacement frontend.
Reapply after changing these files using the existing non-root Vault CLI login:

```sh
python bootstrap/services/authentik_brand.py          # read-only preview
python bootstrap/services/authentik_brand.py --apply  # visual fields only
```

SVG assets use immutable, content-addressed names in Authentik's media storage.
Existing media is never overwritten or deleted. The helper preserves other brand
attributes, flow bindings, certificates, users, providers and MFA settings.
Users' own theme preferences are not changed; the brand default is dark.
