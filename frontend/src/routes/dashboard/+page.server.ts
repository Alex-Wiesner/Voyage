import { redirect } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';
const PUBLIC_SERVER_URL = process.env['PUBLIC_SERVER_URL'];
import type { SlimCollection } from '$lib/types';

const serverEndpoint = PUBLIC_SERVER_URL || 'http://localhost:8000';

const defaultStats = {
	visited_country_count: 0,
	visited_region_count: 0,
	visited_city_count: 0,
	location_count: 0,
	trips_count: 0
};

export const load = (async (event) => {
	if (!event.locals.user) {
		return redirect(302, '/login');
	} else {
		let collections: SlimCollection[] = [];

		let initialFetch = await event.fetch(
			`${serverEndpoint}/api/collections/?order_by=updated_at&order_direction=desc&nested=true`,
			{
				headers: {
					Cookie: `sessionid=${event.cookies.get('sessionid')}`
				},
				credentials: 'include'
			}
		);

		let stats = { ...defaultStats };

		let res = await event.fetch(
			`${serverEndpoint}/api/stats/counts/${event.locals.user.username}/`,
			{
				headers: {
					Cookie: `sessionid=${event.cookies.get('sessionid')}`
				}
			}
		);
		if (!res.ok) {
			console.error('Failed to fetch user stats');
		} else {
			const statsPayload = await res.json();
			stats = {
				...defaultStats,
				...(statsPayload || {})
			};
		}

		if (!initialFetch.ok) {
			let error_message = await initialFetch.json();
			console.error(error_message);
			console.error('Failed to fetch recent collections');
			return redirect(302, '/login');
		} else {
			let res = await initialFetch.json();
			let recentCollections = res.results as SlimCollection[];
			collections = recentCollections.slice(0, 3);
		}

		return {
			props: {
				collections,
				stats
			}
		};
	}
}) satisfies PageServerLoad;
