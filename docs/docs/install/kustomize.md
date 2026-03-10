---
title: kustomize
type: note
permalink: voyage/docs/docs/install/kustomize
---

# Kubernetes and Kustomize (k8s)

_Voyage can be run inside a kubernetes cluster using [kustomize](https://kustomize.io/)._

## Prerequisites

A working kubernetes cluster. Voyage has been tested on k8s, but any Kustomize-capable flavor should be easy to use.

## Cluster Routing

Because the Voyage backend must be reachable by **both** the web browser and the Voyage frontend, k8s-internal routing mechanisms traditional for standing up other similar applications **cannot** be used.

In order to host Voyage in your cluster, you must therefor configure an internally and externally resolvable ingress that routes to your Voyage backend container.

Once you have made said ingress, set `PUBLIC_SERVER_URL` and `PUBLIC_URL` env variables below to the url of that ingress.

## Tailscale and Headscale

Many k8s homelabs choose to use [Tailscale](https://tailscale.com/) or similar projects to remove the need for open ports in your home firewall.

The [Tailscale k8s Operator](https://tailscale.com/kb/1185/kubernetes/) will set up an externally resolvable service/ingress for your Voyage instance,
but it will fail to resolve internally.

You must [expose tailnet IPs to your cluster](https://tailscale.com/kb/1438/kubernetes-operator-cluster-egress#expose-a-tailnet-https-service-to-your-cluster-workloads) so the Voyage pods can resolve them.

## Getting Started

Take a look at the [example config](https://github.com/Alex-Wiesner/voyage/blob/main/kustomization.yml) and modify it for your use case.

## Environment Variables

Look at the [environment variable summary](docker.md#configuration) in the docker install section to see available and required configuration options.

Enjoy Voyage! 🎉