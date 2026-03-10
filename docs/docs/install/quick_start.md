---
title: quick_start
type: note
permalink: voyage/docs/docs/install/quick-start
---

# 🚀 Quick Start Install

Install **Voyage** in seconds using our automated script.

## 🧪 One-Liner Install

```bash
curl -sSL https://get.voyage.app | bash
```

This will:

- Check dependencies (Docker, Docker Compose)
- Set up project directory
- Download required files
- Prompt for basic configuration (like domain name)
- Start Voyage with Docker Compose

## ✅ Requirements

- Docker + Docker Compose
- Linux server or VPS
- Optional: Domain name for HTTPS

## 🔍 What It Does

The script automatically:

1. Verifies Docker is installed and running
2. Downloads `docker-compose.yml` and `.env`
3. Prompts you for domain and port settings
4. Waits for services to start
5. Prints success info with next steps

## 🧼 Uninstall

To remove everything:

```bash
cd voyage
docker compose down -v
rm -rf voyage
```

Need more control? Explore other [install options](getting_started.md) like Docker, Proxmox, Synology NAS, and more.