import { defineConfig } from "vitepress";

// https://vitepress.dev/reference/site-config
export default defineConfig({
  head: [
    ["link", { rel: "icon", href: "/voyage.png" }],

    [
      "script",
      {
        defer: "",
        src: "https://cloud.umami.is/script.js",
        "data-website-id": "a7552764-5a1d-4fe7-80c2-5331e1a53cb6",
      },
    ],
  ],
  ignoreDeadLinks: "localhostLinks",
  title: "Voyage",
  description: "The ultimate travel companion.",
  lang: "en-US",

  sitemap: {
    hostname: "https://voyage.app",
  },

  transformPageData(pageData) {
    if (pageData.relativePath === "index.md") {
      const jsonLd = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        name: "Voyage",
        url: "https://voyage.app",
        applicationCategory: "TravelApplication",
        operatingSystem: "Web, Docker, Linux",
        description:
          "Voyage is a self-hosted platform for tracking and planning travel experiences. Built for modern explorers, it offers trip planning, journaling, tracking and location mapping in one privacy-respecting package.",
        creator: {
          "@type": "Organization",
          name: "Voyage contributors",
          url: "https://github.com/Alex-Wiesner/voyage",
        },
        isBasedOn: "https://github.com/seanmorley15/AdventureLog",
        offers: {
          "@type": "Offer",
          price: "0.00",
          priceCurrency: "USD",
          description: "Open-source version available for self-hosting.",
        },
        softwareVersion: "v0.12.0",
        license: "https://github.com/Alex-Wiesner/voyage/blob/main/LICENSE",
        screenshot:
          "https://raw.githubusercontent.com/Alex-Wiesner/voyage/refs/heads/main/brand/screenshots/adventures.png",
        downloadUrl: "https://github.com/Alex-Wiesner/voyage",
        sameAs: ["https://github.com/Alex-Wiesner/voyage"],
        keywords: [
          "self-hosted travel log",
          "open source trip planner",
          "travel journaling app",
          "docker travel diary",
          "map-based travel tracker",
          "privacy-focused travel app",
          "voyage travel companion",
          "travel experience tracker",
          "self-hosted travel app",
          "open source travel software",
          "trip planning tool",
          "travel itinerary manager",
          "location-based travel app",
          "travel experience sharing",
          "travel log application",
        ],
      };

      return {
        frontmatter: {
          ...pageData.frontmatter,
          head: [
            ["script", { type: "application/ld+json" }, JSON.stringify(jsonLd)],
          ],
        },
      };
    }

    return {};
  },

  themeConfig: {
    // https://vitepress.dev/reference/default-theme-config
    nav: [
      { text: "Home", link: "/" },
      { text: "Docs", link: "/docs/intro/voyage_overview" },
    ],
    search: {
      provider: "local",
    },
    editLink: {
      pattern: "https://github.com/Alex-Wiesner/voyage/edit/main/docs/:path",
    },

    footer: {
      message: "Voyage",
      copyright: "A fork of AdventureLog by Sean Morley",
    },

    logo: "/voyage.png",

    sidebar: [
      {
        text: "About Voyage",
        items: [
          {
            text: "Voyage Overview",
            link: "/docs/intro/voyage_overview",
          },
        ],
      },

      {
        text: "Installation",
        collapsed: false,
        items: [
          { text: "Getting Started", link: "/docs/install/getting_started" },
          { text: "Quick Start Script ⏲️", link: "/docs/install/quick_start" },
          { text: "Docker 🐋", link: "/docs/install/docker" },
          { text: "Proxmox LXC 🐧", link: "/docs/install/proxmox_lxc" },
          { text: "Synology NAS ☁️", link: "/docs/install/synology_nas" },
          {
            text: "Kubernetes and Kustomize 🌐",
            link: "/docs/install/kustomize",
          },
          { text: "Unraid 🧡", link: "/docs/install/unraid" },
          {
            text: "Dev Container + WSL 🧰",
            link: "/docs/install/dev_container_wsl",
          },

          {
            text: "With A Reverse Proxy",
            collapsed: false,
            items: [
              {
                text: "Nginx Proxy Manager",
                link: "/docs/install/nginx_proxy_manager",
              },
              { text: "Traefik", link: "/docs/install/traefik" },
              { text: "Caddy", link: "/docs/install/caddy" },
            ],
          },
        ],
      },
      {
        text: "Usage",
        collapsed: false,
        items: [
          {
            text: "How to use Voyage",
            link: "/docs/usage/usage",
          },
        ],
      },
      {
        text: "Configuration",
        collapsed: false,
        items: [
          {
            text: "Immich Integration",
            link: "/docs/configuration/immich_integration",
          },
          {
            text: "Google Maps Integration",
            link: "/docs/configuration/google_maps_integration",
          },
          {
            text: "Strava Integration",
            link: "/docs/configuration/strava_integration",
          },
          {
            text: "Wanderer Integration",
            link: "/docs/configuration/wanderer_integration",
          },
          {
            text: "Social Auth and OIDC",
            link: "/docs/configuration/social_auth",
          },
          {
            text: "Authentication Providers",
            collapsed: false,
            items: [
              {
                text: "Authentik",
                link: "/docs/configuration/social_auth/authentik",
              },
              {
                text: "GitHub",
                link: "/docs/configuration/social_auth/github",
              },
              {
                text: "Authelia",
                link: "https://www.authelia.com/integration/openid-connect/adventure-log/",
              },
              {
                text: "Pocket ID",
                link: "/docs/configuration/social_auth/pocket_id",
              },
              {
                text: "Open ID Connect",
                link: "/docs/configuration/social_auth/oidc",
              },
            ],
          },
          {
            text: "Update App",
            link: "/docs/configuration/updating",
          },
          {
            text: "Disable Registration",
            link: "/docs/configuration/disable_registration",
          },
          { text: "SMTP Email", link: "/docs/configuration/email" },
          { text: "Umami Analytics", link: "/docs/configuration/analytics" },
          {
            text: "Advanced Configuration",
            link: "/docs/configuration/advanced_configuration",
          },
        ],
      },
      {
        text: "Troubleshooting",
        collapsed: true,
        items: [
          {
            text: "No Images Displaying",
            link: "/docs/troubleshooting/no_images",
          },
          {
            text: "Login and Registration Unresponsive",
            link: "/docs/troubleshooting/login_unresponsive",
          },
          {
            text: "Failed to Start Nginx",
            link: "/docs/troubleshooting/nginx_failed",
          },
        ],
      },
      {
        text: "Guides",
        collapsed: true,
        items: [
          {
            text: "Travel Agent (MCP)",
            link: "/docs/guides/travel_agent",
          },
          {
            text: "Admin Panel",
            link: "/docs/guides/admin_panel",
          },
          {
            text: "Invite a User",
            link: "/docs/guides/invite_user",
          },
          {
            text: "v0.7.1 Migration Guide",
            link: "/docs/guides/v0-7-1_migration",
          },
        ],
      },
      {
        text: "Changelogs",
        collapsed: true,
        items: [
          {
            text: "Development Timeline",
            link: "/docs/changelogs/development_timeline",
          },
          {
            text: "v0.12.0",
            link: "/docs/changelogs/v0-12-0",
          },
          {
            text: "v0.11.0",
            link: "/docs/changelogs/v0-11-0",
          },
          {
            text: "v0.10.0",
            link: "/docs/changelogs/v0-10-0",
          },
          {
            text: "v0.9.0",
            link: "/docs/changelogs/v0-9-0",
          },
          {
            text: "v0.8.0",
            link: "/docs/changelogs/v0-8-0",
          },
          {
            text: "v0.7.1",
            link: "/docs/changelogs/v0-7-1",
          },
          {
            text: "v0.7.0",
            link: "/docs/changelogs/v0-7-0",
          },
        ],
      },
    ],

    socialLinks: [
      { icon: "github", link: "https://github.com/Alex-Wiesner/voyage" },
    ],
  },
});
