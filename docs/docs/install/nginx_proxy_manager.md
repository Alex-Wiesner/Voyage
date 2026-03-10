---
title: nginx_proxy_manager
type: note
permalink: voyage/docs/docs/install/nginx-proxy-manager
---

# Installation with Nginx Proxy Manager

Nginx Proxy Manager is a simple and powerful tool that allows you to manage Nginx proxy hosts and SSL certificates. It is designed to be easy to use and configure, and it integrates well with Docker.

It is fairly simple to set up Nginx Proxy Manager with Voyage.

## Deploy Voyage using Docker

View the [Docker installation guide](docker.md) for instructions on how to deploy Voyage using Docker.

## Ensure Correct Environment Variables

- `ORIGIN` - The domain where you will be hosting Voyage. This is where the **frontend** will be served from.
- `PUBLIC_URL` - This needs to match the **outward port of the server** and be accessible from where the app is used. It is used for the creation of image URLs.

## Setup Docker Network

Ensure that the Nginx Proxy Manager and Voyage containers are on the same Docker network. You can create a new network using the following command:

```bash
docker network create nginx-proxy-manager
```

Add the following to the bottom of the `docker-compose.yml` file for the Nginx Proxy Manager service and the Voyage service.

```yaml
networks:
  default:
    name: nginx-proxy-manager
    external: true
```

## Setting Up Nginx Proxy Manager

1. Install Nginx Proxy Manager on your server. You can find the installation instructions [here](https://nginxproxymanager.com/setup/).
2. Open the Nginx Proxy Manager web interface and log in with your credentials.
3. Add a new proxy host for the Voyage **frontend**:
   - **Domain Names**: Enter the domain name where you will be hosting Voyage.
   - **Scheme**: `http`
   - **Forward Hostname/IP**: `voyage-frontend` The name of the Voyage **frontend** container in the `docker-compose.yml` file.
   - **Forward Port**: `3000` This is the internal port of the Voyage **frontend** container so you will not need to change it even if you change the external port.
4. Add a new proxy host for the Voyage **backend**:
   - **Domain Names**: Enter the domain name where you will be hosting Voyage.
   - **Scheme**: `http`
   - **Forward Hostname/IP**: `voyage-backend` The name of the Voyage **backend** container in the `docker-compose.yml` file.
   - **Forward Port**: `80` This is the internal port of the Voyage **backend** container so you will not need to change it even if you change the external port.

This will allow you to access Voyage using the domain name you specified in the Nginx Proxy Manager configuration.