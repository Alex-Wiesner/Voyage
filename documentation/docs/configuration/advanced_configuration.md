# Advanced Configuration

In addition to the primary configuration variables listed above, there are several optional environment variables that can be set to further customize your Voyage instance. These variables are not required for a basic setup but can enhance functionality and security.

| Name                         | Required | Description                                                                                                                                                                                | Default Value | Variable Location |
| ---------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------- | ----------------- |
| `ACCOUNT_EMAIL_VERIFICATION` | No       | Enable email verification for new accounts. Options are `none`, `optional`, or `mandatory`                                                                                                 | `none`        | Backend           |
| `FORCE_SOCIALACCOUNT_LOGIN`  | No       | When set to `True`, only social login is allowed (no password login). The login page will show only social providers or redirect directly to the first provider if only one is configured. | `False`       | Backend           |
| `SOCIALACCOUNT_ALLOW_SIGNUP` | No       | When set to `True`, signup will be allowed via social providers even if registration is disabled.                                                                                          | `False`       | Backend           |
| `OSRM_BASE_URL`             | No       | Base URL of the OSRM routing server used for itinerary connector distance/travel-time metrics. The public OSRM demo server is used by default. Set this to point at your own OSRM instance (e.g. `http://osrm:5000`) for higher rate limits or offline use. When the OSRM server is unreachable, the backend automatically falls back to haversine-based approximations so the itinerary UI always shows metrics. | `https://router.project-osrm.org` | Backend           |
| `FIELD_ENCRYPTION_KEY`      | No*      | Fernet key used to encrypt user API keys at rest (integrations API key storage). Generate a 32-byte urlsafe base64 key (e.g. `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`). If missing/invalid, only API-key storage endpoints fail gracefully and the rest of the app remains available. | _(none)_ | Backend |
| `DJANGO_MCP_ENDPOINT`       | No       | HTTP path used for the Voyage Travel Agent MCP endpoint. Clients call this endpoint with `Authorization: Token <token>` using a DRF auth token for the target user account.                                                        | `api/mcp`     | Backend           |

## MCP endpoint authentication details

Voyage's MCP endpoint requires token authentication.

- Header format: `Authorization: Token <token>`
- Default endpoint path: `api/mcp`
- Override path with: `DJANGO_MCP_ENDPOINT`
- Token bootstrap endpoint for authenticated sessions: `GET /auth/mcp-token/`

For MCP usage patterns and tool-level examples, see the [Travel Agent (MCP) guide](../guides/travel_agent.md).
