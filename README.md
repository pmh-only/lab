<div align="center">

<img src="./docs/flashlight.svg" width="60px"/>

# pmh-only/lab
Kubernetes Manifest Files for [My Homelab Server](https://pmh.codes)

<br />
<br />
</div>

## How it works?
An [ArgoCD instance](https://argo.pmh.codes/) continuously monitors the [apps folder](https://github.com/pmh-only/lab/tree/main/apps), which contains manifest files that [reference each application's manifest directory](https://argo.pmh.codes/applications/argocd/apps).
When updates occur, these manifests trigger full resource synchronization.

At the same time, the ArgoCD Image Updater ensures that container images always stay up to date with the latest versions.

## Traffic routes
```mermaid
flowchart TD
    A([User Request])
    A a1@-->|TLSv1.3 / QUIC| B
    B{"
        User's DNS
        resolver decision
    "}
    B a2@--> E1
    B a3@--> E2
    B a4@--> E3
    subgraph C[Kubernetes Cluster]
    subgraph D1[Node: pmhoci]
        E1["
            Gateway pod
            (nginx)
        "]
        H1[App1 pod]
    end
    subgraph D2[Node: pmhoci2]
        E2["
            Gateway pod
            (nginx)
        "]
        F["
            Ingress Nginx
            controller pod
        "]
        G{"
            Routing decision
            by Host header
        "}
        H2[App2 pod]
    end
    subgraph D3[Node: pmhoci3]
        E3["
            Gateway pod
            (nginx)
        "]
        H3[App3 pod]
    end

    E1 a5@--> F
    E2 a6@-->|Terminates TLS| F
    E3 a7@--> F
    F a8@--> G
    G a9@--> H1
    G a10@--> H2
    G a11@--> H3
    end

    a1@{ animation: fast }
    a2@{ animation: fast }
    a3@{ animation: fast }
    a4@{ animation: fast }
    a5@{ animation: fast }
    a6@{ animation: fast }
    a7@{ animation: fast }
    a8@{ animation: fast }
    a9@{ animation: fast }
    a10@{ animation: fast }
    a11@{ animation: fast }
```
