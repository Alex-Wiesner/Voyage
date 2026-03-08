# How to use Voyage

Welcome to Voyage! This guide will help you get started with Voyage and provide you with an overview of the features available to you.

Voyage also includes a Travel Agent MCP interface for authenticated programmatic trip access and itinerary actions. See the [Travel Agent (MCP) guide](../guides/travel_agent.md).

## Key Terms

#### Locations

::: tip Terminology Update
**Location has replaced Adventure:**  
The term "Location" is now used instead of "Adventure" - the usage remains the same, just the name has changed to better reflect the purpose of the feature.
:::

- **Location**: think of a location as a point on a map, a place you want to visit, have visited, or a place you want to explore. A location can be anything you want it to be, from a local park to a famous landmark. These are the building blocks of Voyage and are the fundamental unit of information in the app.
- **Visit**: a visit is added to an location. It contains a date and notes about when the location was visited. If a location is visited multiple times, multiple visits can be added. If there are no visits on a location or the date of all visits is in the future, the location is considered planned. If the date of the visit is in the past, the location is considered completed.
- **Category**: a category is a way to group locations together. For example, you could have a category for parks, a category for museums, and a category for restaurants.
- **Tag**: a tag is a way to add additional information to a location. For example, you could have a tag for the type of cuisine at a restaurant or the type of art at a museum. Multiple tags can be added to a location.
- **Image**: an image is a photo that is added to a location. Images can be added to a location to provide a visual representation or to capture a memory of the visit. These can be uploaded from your device or with a service like [Immich](/docs/configuration/immich_integration) if the integration is enabled.
- **Attachment**: an attachment is a file that is added to a location. Attachments can be added to a location to provide additional information, such as a map of the location or a brochure from the visit.
- **Trail**: a trail is a path or route that is associated with a location. Trails can be used to document hiking paths, biking routes, or any other type of journey that has a specific path. Trails are linked to locations either by link to an external service (e.g., AllTrails) or from the [Wanderer](/docs/configuration/wanderer_integration) integration. When linked via the Wanderer integration, trails can provide additional context and information about the journey such as distance and elevation gain.
- **Activity**: an activity is what you actually do at a location. This can include things like hiking, biking, skiing, kayaking, or any other outdoor activity. Activities are associated with a visit and include fields such as the type of activity, time, distance, and trail taken. They can be manually entered or imported from the [Strava](/docs/configuration/strava_integration) integration. Once an activity is added, it will appear on the location map based on the data from the GPX file.

#### Collections

- **Collection**: a collection is a way to group locations together. Collections are flexible and can be used in many ways. When no start or end date is added to a collection, it acts like a folder to group locations together. When a start and end date is added to a collection, it acts like a trip to group locations together that were visited during that time period. With start and end dates, the collection is transformed into a full itinerary with a timeline-style day view — each day displays numbered stops as compact cards (without image banners), connector rows between consecutive locations showing distance and travel time via OSRM routing (walking if ≤ 20 min, driving otherwise) with automatic haversine fallback when OSRM is unavailable, and a single `+ Add` control for inserting new places. Lodging placement follows directional rules: on check-in day it appears after the last stop, on check-out day it appears before the first stop, and on days with no locations a single lodging card is shown (or two cards when a checkout and checkin are different lodgings). Connector rows link lodging to adjacent locations. Day-level quick actions include Auto-fill (populates an empty itinerary from dated records) and Optimize (nearest-neighbor route ordering for coordinate-backed stops). The day date pill displays a weather temperature summary when available, with graceful fallback if weather data is unavailable. The itinerary also includes a map showing the route taken between locations. Your most recently updated collections also appear on the dashboard. For example, you could have a collection for a trip to Europe with dates so you can plan where you want to visit, a collection of local hiking trails, or a collection for a list of restaurants you want to try.
- **Transportation**: a transportation is a collection exclusive feature that allows you to add transportation information to your trip. In the itinerary timeline view, transportation items appear as compact cards (same style as location cards — no image banners) showing the travel mode, duration, and distance. Connector rows adjacent to transportation use directional coordinates: the row before a transportation segment measures distance to the transportation's origin, while the row after measures distance from its destination. This can be used to show the route taken between locations and the mode of transportation used. It can also be used to track flight information, such as flight number and departure time.
- **Lodging**: a lodging is a collection exclusive feature that allows you to add lodging information to your trip. This can be used to plan where you will stay during your trip and add notes about the lodging location. It can also be used to track reservation information, such as reservation number and check-in time. In the itinerary timeline view, lodging is displayed as compact cards (without image headers) using directional placement: on check-in day the lodging card appears after the last stop, on check-out day it appears before the first stop, and on days with no locations a single card is shown unless the checkout and checkin are different lodgings (in which case both appear). Lodging added from within a specific day is automatically scheduled to that day. Connector rows show boundary transitions between lodging and adjacent locations.
- **Note**: a note is a collection exclusive feature that allows you to add notes to your trip. This can be used to add additional information about your trip, such as a summary of the trip or a list of things to do. Notes can be assigned to a specific day of the trip to help organize the information.
- **Checklist**: a checklist is a collection exclusive feature that allows you to add a checklist to your trip. This can be used to create a list of things to do during your trip or for planning purposes like packing lists. Checklists can be assigned to a specific day of the trip to help organize the information.

#### World Travel

- **World Travel**: the world travel feature of Voyage allows you to track the countries, regions, and cities you have visited during your lifetime. You can add visits to countries, regions, and cities, and view statistics about your travels. The world travel feature is a fun way to visualize where you have been and where you want to go next.
  - **Country**: a country is a geographical area that is recognized as an independent nation. You can add visits to countries to track where you have been.
  - **Region**: a region is a geographical area that is part of a country. You can add visits to regions to track where you have been within a country.
  - **City**: a city is a geographical area that is a populated urban center. You can add visits to cities to track where you have been within a region.

## Tutorial Video

<iframe width="560" height="315" src="https://www.youtube.com/embed/4Y2LvxG3xn4" title="YouTube video player" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>
