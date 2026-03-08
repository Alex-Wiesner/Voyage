# About Voyage

> **Voyage is a fork of [AdventureLog](https://github.com/seanmorley15/AdventureLog)**, the open-source travel companion created by [Sean Morley](https://seanmorley.com). Voyage builds on AdventureLog's foundation to make additional changes and improvements.

Voyage is a full-fledged travel companion. With Voyage, you can log your adventures, keep track of where you've been on the world map, plan your next trip collaboratively, and share your experiences with friends and family. **Voyage is the ultimate travel companion for the modern-day explorer**.

## Features

- **Track Your Adventures** 🌍: Log your adventures and keep track of where you've been on the world map.
  - Locations can store a variety of information, including the location, date, and description.
  - Locations can be sorted into custom categories for easy organization.
  - Locations can be marked as private or public, allowing you to share your adventures with friends and family.
  - Keep track of the countries and regions you've visited with the world travel book.
  - Upload trails and activities to your locations to remember your experiences with detailed maps and stats.
- **Plan Your Next Trip** 📃: Take the guesswork out of planning your next adventure with an easy-to-use itinerary planner.
  - Itineraries can be created for any number of days and can include multiple destinations.
  - A timeline-style day view shows ordered stops with numbered markers and compact location cards (no image banners) for a dense overview. Lodging placement follows directional rules: on check-in day lodging appears after the last stop, on check-out day it appears before the first stop, and on days with no locations a single lodging card is shown (or two cards when a checkout and checkin are different lodgings). Lodging cards use the same compact style (no image header) as location cards within the itinerary.
  - Connector rows between adjacent items display distance and travel time powered by [OSRM](https://project-osrm.org/) routing (walking if ≤ 20 min, driving otherwise), with automatic haversine fallback when OSRM is unavailable. Self-hosted OSRM instances are supported via the `OSRM_BASE_URL` environment variable. Transportation items appear as compact cards (same style as location cards — no image banners) showing mode, duration, and distance; connector routing uses the transportation's origin coordinates when approaching and destination coordinates when departing. Boundary transitions between lodging and adjacent stops are also shown as connector rows.
  - Each day has a single `+ Add` control to insert new places, and day-level quick actions include Auto-fill and Optimize (nearest-neighbor ordering for coordinate-backed stops). The day date pill includes a weather temperature summary when available. Lodging added from within a day is automatically scheduled to that day.
  - Itineraries include many planning features like flight information, notes, checklists, and links to external resources.
  - Itineraries can be shared with friends and family for collaborative planning.
- **Share Your Experiences** 📸: Share your adventures with friends and family and collaborate on trips together.
  - Locations and itineraries can be shared via a public link or directly with other Voyage users.
  - Collaborators can view and edit shared itineraries (collections), making planning a breeze.
- **Customizable Themes** 🎨: Choose from 10 built-in themes including Light, Dark, Dim, Night, Forest, Aqua, Catppuccin Mocha, Aesthetic Light, Aesthetic Dark, and Northern Lights. Theme selection persists across sessions.
- **Travel Agent (MCP) access** 🤖: Voyage exposes an authenticated MCP endpoint so external clients can list collections, inspect itineraries, create itinerary items, and reorder trip timelines. See the [Travel Agent (MCP) guide](../guides/travel_agent.md).

## Why Voyage?

Voyage inherits AdventureLog's mission: to provide a modern, open-source, user-friendly alternative to travel apps that are too complex, too expensive, or too closed off. Voyage builds on this foundation with additional changes and improvements.

### Open Source (GPL-3.0)

Voyage is open-source software, licensed under the GPL-3.0 license. This means that you are free to use, modify, and distribute Voyage as you see fit. The source code is available on GitHub, and contributions are welcome from anyone who wants to help improve the project.

## Upstream Project

Voyage is a fork of [AdventureLog](https://github.com/seanmorley15/AdventureLog), created by [Sean Morley](https://seanmorley.com). Credit and thanks go to Sean and all contributors to the original project for building the foundation that Voyage is built upon.
