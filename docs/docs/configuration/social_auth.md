---
title: social_auth
type: note
permalink: voyage/docs/docs/configuration/social-auth
---

# Social Authentication

Voyage support authentication via 3rd party services and self-hosted identity providers. Once these services are enabled, users can log in to Voyage using their accounts from these services and link existing Voyage accounts to these services for easier access.

The steps for each service varies so please refer to the specific service's documentation for more information.

## Supported Services

- [Authentik](social_auth/authentik.md) (self-hosted)
- [GitHub](social_auth/github.md)
- [Open ID Connect](social_auth/oidc.md)
- [Authelia](https://www.authelia.com/integration/openid-connect/voyage/)

## Linking Existing Accounts

If you already have an Voyage account and would like to link it to a 3rd party service, you can do so by logging in to Voyage and navigating to the `Account Settings` page. From there, scroll down to `Social and OIDC Authentication` and click the `Launch Account Connections` button. If identity providers have been enabled on your instance, you will see a list of available services to link to.