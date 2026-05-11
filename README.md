![](./docs/banner.png)


# pmh-only/lab

<img src="./docs/flashlight.svg" width="90px" align="right"/>

**lab** is the Single source of truth repository contains Kubernetes resource manifest files for my Homelab GitOps environment powered by ArgoCD.

Covered domains include, but are not limited to, apex and subdomains of https://pmh.codes and https://pmh.so.

An ArgoCD instance continuously monitors the apps folder, which contains manifest files that reference each application's manifest directory. When updates occur, these manifests trigger full resource synchronization. More information of this structure is [here: [App of Apps]](https://argo-cd.readthedocs.io/en/stable/operator-manual/cluster-bootstrapping/#app-of-apps-pattern-alternative)

At the same time, the ArgoCD Image Updater ensures that container images always stay up to date with the latest versions.

## Contents
This repository defines many components of Kubernetes cluster such as:
* Public Domain Name Server / Private Resolver (Technitium DNS Server)
* HTTP Routings/Rewrites (Customed DaemonSet Gateway, Envoy Gateway)
* TLS Certificate Management/Ordering (cert-manager)
* Static Website Serving (RustFS)
* SQL/No-SQL Databases (MySQL, PostgreSQL, MongoDB, Redis)
* Observabilities (Grafana, Prometheus, Thanos)
* Public Gateway / Internal Connector of my Tailscale Network
* Encrypted Secrets (SealedSecret)
* Volumn and Cluster Backup Schedule (Velero, Kopia)
* and Actual Service Components.

## Sync Status
<!-- SYNC_TABLE_START -->

<table>
  
  <tr>
  <td><img src="https://argo.pmh.codes/api/badge?name=authentik&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=bitwarden&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=books&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=bot&revision=false&showAppName=true" width="200px" /><br /></td>
  </tr>
  
  <tr>
  <td><img src="https://argo.pmh.codes/api/badge?name=cert-manager&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=cert-manager-technitium-webhook&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=chatsolution&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=code-server&revision=false&showAppName=true" width="200px" /><br /></td>
  </tr>
  
  <tr>
  <td><img src="https://argo.pmh.codes/api/badge?name=code-server-route&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=database&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=descheduler&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=envoy-gateway&revision=false&showAppName=true" width="200px" /><br /></td>
  </tr>
  
  <tr>
  <td><img src="https://argo.pmh.codes/api/badge?name=gateway&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=ghost&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=go&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=guessaiword&revision=false&showAppName=true" width="200px" /><br /></td>
  </tr>
  
  <tr>
  <td><img src="https://argo.pmh.codes/api/badge?name=heartbeat&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=here&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=immich&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=indexgen&revision=false&showAppName=true" width="200px" /><br /></td>
  </tr>
  
  <tr>
  <td><img src="https://argo.pmh.codes/api/badge?name=keysboard&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=kopia&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=mail&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=meta&revision=false&showAppName=true" width="200px" /><br /></td>
  </tr>
  
  <tr>
  <td><img src="https://argo.pmh.codes/api/badge?name=minecraft&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=minio&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=minio-customs&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=mntserver&revision=false&showAppName=true" width="200px" /><br /></td>
  </tr>
  
  <tr>
  <td><img src="https://argo.pmh.codes/api/badge?name=monitoring&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=nameserver&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=notaikr&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=office&revision=false&showAppName=true" width="200px" /><br /></td>
  </tr>
  
  <tr>
  <td><img src="https://argo.pmh.codes/api/badge?name=openebs-zfs&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=pdf&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=pdf-configs&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=pmhso&revision=false&showAppName=true" width="200px" /><br /></td>
  </tr>
  
  <tr>
  <td><img src="https://argo.pmh.codes/api/badge?name=radio&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=reloader&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=run&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=seafile&revision=false&showAppName=true" width="200px" /><br /></td>
  </tr>
  
  <tr>
  <td><img src="https://argo.pmh.codes/api/badge?name=sealedsecrets&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=solver&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=spotify&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=tailscale&revision=false&showAppName=true" width="200px" /><br /></td>
  </tr>
  
  <tr>
  <td><img src="https://argo.pmh.codes/api/badge?name=tailscale-configs&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=terms&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=thepool&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=trace&revision=false&showAppName=true" width="200px" /><br /></td>
  </tr>
  
  <tr>
  <td><img src="https://argo.pmh.codes/api/badge?name=traffic&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=txt&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=velero&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=velero-ui&revision=false&showAppName=true" width="200px" /><br /></td>
  </tr>
  
  <tr>
  <td><img src="https://argo.pmh.codes/api/badge?name=velero-ui-configs&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=visualized&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=welplan&revision=false&showAppName=true" width="200px" /><br /></td>
  
  
  
  <td><img src="https://argo.pmh.codes/api/badge?name=workflows&revision=false&showAppName=true" width="200px" /><br /></td>
  </tr>
  
</table>

<!-- SYNC_TABLE_END -->
    
    

## Acknowledges
&copy; 2024-2026. Minhyeok Park <pmh_only@pmh.codes>. MIT Licensed.

This repository contains some of contents from previous repository: [pmh-only/composes](https://github.com/pmh-only/composes).
