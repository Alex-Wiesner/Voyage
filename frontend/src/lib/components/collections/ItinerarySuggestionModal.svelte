<script lang="ts">
	import { createEventDispatcher, onMount } from 'svelte';
	import { t } from 'svelte-i18n';
	import type { Collection } from '$lib/types';

	export let collection: Collection;
	export let user: any;
	export let targetDate: string;
	export let displayDate: string;
	$: void user;

	type SuggestionCategory = 'restaurant' | 'activity' | 'event' | 'lodging' | 'surprise';
	type SuggestionItem = {
		name: string;
		description?: string;
		why_fits?: string;
		category?: string;
		location?: string;
		rating?: number | string | null;
		price_level?: string | null;
		latitude?: number | string | null;
		longitude?: number | string | null;
	};

	const dispatch = createEventDispatcher();

	let modal: HTMLDialogElement;
	let step = 0; // 0: category, 1: filters, 2: results
	let selectedCategory: SuggestionCategory | '' = '';
	let filters: Record<string, any> = {};
	let suggestions: SuggestionItem[] = [];
	let isLoading = false;
	let isAdding = false;
	let addingSuggestionName = '';
	let error = '';

	const categories: Array<{
		id: SuggestionCategory;
		icon: string;
		labelKey: string;
		skipFilters?: boolean;
	}> = [
		{ id: 'restaurant', icon: '🍽️', labelKey: 'suggestions.category_restaurant' },
		{ id: 'activity', icon: '🎯', labelKey: 'suggestions.category_activity' },
		{ id: 'event', icon: '🎉', labelKey: 'suggestions.category_event' },
		{ id: 'lodging', icon: '🏨', labelKey: 'suggestions.category_lodging' },
		{ id: 'surprise', icon: '✨', labelKey: 'suggestions.surprise_me', skipFilters: true }
	];

	const supportedApiCategories = ['restaurant', 'activity', 'event', 'lodging'];
	const LOCATION_MODEL_TEXT_MAX_LENGTH = 200;

	const activityTypes = ['outdoor', 'cultural', 'entertainment', 'other'];
	const durations = ['few hours', 'half-day', 'full-day'];
	const timePreferences = ['morning', 'afternoon', 'evening', 'night'];
	const lodgingTypes = ['hotel', 'hostel', 'apartment', 'resort'];
	const amenities = ['wifi', 'pool', 'parking', 'breakfast'];

	onMount(() => {
		modal = document.getElementById('suggestion_modal') as HTMLDialogElement;
		if (modal) modal.showModal();
	});

	function getCollectionLocation(): string {
		const firstLocation = collection?.locations?.[0];
		if (!firstLocation) return collection?.name || '';
		return (
			firstLocation.location ||
			firstLocation.city?.name ||
			firstLocation.country?.name ||
			firstLocation.name ||
			collection?.name ||
			''
		);
	}

	function close() {
		dispatch('close');
	}

	function resetFiltersForCategory(category: SuggestionCategory) {
		if (category === 'restaurant') {
			filters = { cuisine_type: '', price_range: '', dietary: '' };
		} else if (category === 'activity') {
			filters = { activity_type: '', duration: '' };
		} else if (category === 'event') {
			filters = { event_type: '', time_preference: '' };
		} else if (category === 'lodging') {
			filters = { lodging_type: '', amenities: [] };
		} else {
			filters = {};
		}
	}

	async function selectCategory(category: SuggestionCategory, skipFilters = false) {
		selectedCategory = category;
		error = '';
		suggestions = [];
		resetFiltersForCategory(category);

		if (skipFilters) {
			await fetchSuggestions();
			return;
		}

		step = 1;
	}

	function getApiCategory(): string {
		if (selectedCategory !== 'surprise') return selectedCategory;
		const randomIndex = Math.floor(Math.random() * supportedApiCategories.length);
		return supportedApiCategories[randomIndex];
	}

	function getActiveFilters() {
		if (selectedCategory === 'surprise') return {};
		const nextFilters: Record<string, any> = {};
		Object.entries(filters || {}).forEach(([key, value]) => {
			if (Array.isArray(value) && value.length > 0) nextFilters[key] = value;
			else if (!Array.isArray(value) && value) nextFilters[key] = value;
		});
		return nextFilters;
	}

	function asRecord(value: unknown): Record<string, unknown> | null {
		if (!value || typeof value !== 'object' || Array.isArray(value)) {
			return null;
		}
		return value as Record<string, unknown>;
	}

	function normalizeText(value: unknown): string {
		if (typeof value !== 'string') return '';
		return value.trim();
	}

	function truncateToModelSafeLength(value: string): string {
		return value.slice(0, LOCATION_MODEL_TEXT_MAX_LENGTH);
	}

	function normalizeRating(value: unknown): number | null {
		if (typeof value === 'number' && Number.isFinite(value)) {
			return value;
		}

		if (typeof value === 'string') {
			const match = value.match(/\d+(\.\d+)?/);
			if (!match) return null;
			const parsed = Number(match[0]);
			return Number.isFinite(parsed) ? parsed : null;
		}

		return null;
	}

	function normalizeCoordinate(value: unknown): number | null {
		if (typeof value === 'number' && Number.isFinite(value)) {
			return value;
		}

		if (typeof value === 'string') {
			const parsed = Number(value.trim());
			return Number.isFinite(parsed) ? parsed : null;
		}

		return null;
	}

	function normalizeSuggestionItem(value: unknown): SuggestionItem | null {
		const item = asRecord(value);
		if (!item) return null;

		const name =
			normalizeText(item.name) ||
			normalizeText(item.title) ||
			normalizeText(item.place_name) ||
			normalizeText(item.venue);
		const description =
			normalizeText(item.description) || normalizeText(item.summary) || normalizeText(item.details);
		const whyFits =
			normalizeText(item.why_fits) || normalizeText(item.whyFits) || normalizeText(item.reason);
		const location =
			normalizeText(item.location) ||
			normalizeText(item.address) ||
			normalizeText(item.neighborhood);
		const category = normalizeText(item.category);
		const priceLevel =
			normalizeText(item.price_level) ||
			normalizeText(item.priceLevel) ||
			normalizeText(item.price);
		const rating = normalizeRating(item.rating ?? item.score);
		const latitude = normalizeCoordinate(item.latitude ?? item.lat);
		const longitude = normalizeCoordinate(item.longitude ?? item.lon ?? item.lng);

		const finalName = name || location;
		if (!finalName) return null;

		return {
			name: finalName,
			description: description || undefined,
			why_fits: whyFits || undefined,
			category: category || undefined,
			location: location || undefined,
			rating,
			price_level: priceLevel || null,
			latitude,
			longitude
		};
	}

	function buildLocationPayload(suggestion: SuggestionItem) {
		const resolvedName =
			normalizeText(suggestion.name) || normalizeText(suggestion.location) || 'Suggestion';
		const name = truncateToModelSafeLength(resolvedName);
		const resolvedLocation =
			normalizeText(suggestion.location) ||
			getCollectionLocation() ||
			normalizeText(suggestion.name) ||
			name;
		const locationText = truncateToModelSafeLength(resolvedLocation || name);
		const description =
			normalizeText(suggestion.description) ||
			normalizeText(suggestion.why_fits) ||
			(suggestion.category ? `${suggestion.category} suggestion` : '');
		const rating = normalizeRating(suggestion.rating);
		const latitude = normalizeCoordinate(suggestion.latitude);
		const longitude = normalizeCoordinate(suggestion.longitude);

		return {
			name,
			description,
			location: locationText || name,
			rating,
			latitude,
			longitude,
			collections: [collection.id],
			is_public: Boolean(collection?.is_public)
		};
	}

	async function fetchSuggestions() {
		if (!selectedCategory) return;

		step = 2;
		error = '';
		isLoading = true;

		try {
			const response = await fetch('/api/chat/suggestions/day/', {
				method: 'POST',
				credentials: 'include',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					collection_id: collection.id,
					date: targetDate,
					category: getApiCategory(),
					filters: getActiveFilters(),
					location_context: getCollectionLocation()
				})
			});

			if (!response.ok) {
				throw new Error('Failed to get suggestions');
			}

			const data = await response.json();
			suggestions = Array.isArray(data?.suggestions)
				? data.suggestions
						.map((item: unknown) => normalizeSuggestionItem(item))
						.filter((item: SuggestionItem | null): item is SuggestionItem => item !== null)
				: [];
		} catch (_err) {
			error = $t('suggestions.error');
			suggestions = [];
		} finally {
			isLoading = false;
		}
	}

	function goBackToFilters() {
		error = '';
		suggestions = [];
		step = selectedCategory === 'surprise' ? 0 : 1;
	}

	function toggleAmenity(value: string, enabled: boolean) {
		const currentAmenities = Array.isArray(filters.amenities) ? filters.amenities : [];
		if (enabled) {
			filters = { ...filters, amenities: [...new Set([...currentAmenities, value])] };
			return;
		}
		filters = { ...filters, amenities: currentAmenities.filter((a: string) => a !== value) };
	}

	function handleAmenityChange(value: string, event: Event) {
		toggleAmenity(value, (event.currentTarget as HTMLInputElement).checked);
	}

	async function handleAddSuggestion(suggestion: SuggestionItem) {
		if (!suggestion?.name || isAdding) return;

		isAdding = true;
		addingSuggestionName = suggestion.name;
		error = '';

		try {
			const payload = buildLocationPayload(suggestion);
			const createLocationResponse = await fetch('/api/locations/', {
				method: 'POST',
				credentials: 'include',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(payload)
			});

			if (!createLocationResponse.ok) {
				throw new Error('Failed to create location');
			}

			const location = await createLocationResponse.json();
			if (!location?.id) {
				throw new Error('Location was not created');
			}

			dispatch('addItem', {
				type: 'location',
				itemId: location.id,
				updateDate: false,
				location
			});
		} catch (_err) {
			error = $t('suggestions.error');
		} finally {
			isAdding = false;
			addingSuggestionName = '';
		}
	}
</script>

<dialog id="suggestion_modal" class="modal backdrop-blur-sm">
	<div
		class="modal-box w-11/12 max-w-4xl bg-gradient-to-br from-base-100 via-base-100 to-base-200 border border-base-300 shadow-2xl"
	>
		<div
			class="sticky top-0 z-10 bg-base-100/90 backdrop-blur-lg border-b border-base-300 -mx-6 -mt-6 px-6 py-4 mb-6"
		>
			<h3 class="text-lg font-bold text-primary">
				{$t('suggestions.title')}
				{$t('suggestions.for_date').replace('{date}', displayDate)}
			</h3>
		</div>

		<div class="px-2 max-h-[28rem] overflow-y-auto space-y-4">
			{#if step === 0}
				<p class="text-sm opacity-80">{$t('suggestions.select_category')}</p>
				<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
					{#each categories as category}
						<button
							type="button"
							class="btn btn-outline justify-start h-auto py-4"
							on:click={() => selectCategory(category.id, !!category.skipFilters)}
						>
							<span class="text-lg">{category.icon}</span>
							<span>{$t(category.labelKey)}</span>
						</button>
					{/each}
				</div>
			{:else if step === 1}
				<p class="text-sm opacity-80">{$t('suggestions.refine_filters')}</p>

				{#if selectedCategory === 'restaurant'}
					<label class="form-control w-full">
						<div class="label">
							<span class="label-text">{$t('suggestions.cuisine_type')}</span>
						</div>
						<input class="input" type="text" bind:value={filters.cuisine_type} />
					</label>

					<label class="form-control w-full">
						<div class="label"><span class="label-text">{$t('suggestions.price_range')}</span></div>
						<select class="select" bind:value={filters.price_range}>
							<option value="">{$t('recomendations.any')}</option>
							<option value="$">$</option>
							<option value="$$">$$</option>
							<option value="$$$">$$$</option>
							<option value="$$$$">$$$$</option>
						</select>
					</label>

					<label class="form-control w-full">
						<div class="label"><span class="label-text">{$t('suggestions.dietary')}</span></div>
						<input class="input" type="text" bind:value={filters.dietary} />
					</label>
				{:else if selectedCategory === 'activity'}
					<label class="form-control w-full">
						<div class="label">
							<span class="label-text">{$t('suggestions.activity_type')}</span>
						</div>
						<select class="select" bind:value={filters.activity_type}>
							<option value="">{$t('recomendations.any')}</option>
							{#each activityTypes as activityType}
								<option value={activityType}>{activityType}</option>
							{/each}
						</select>
					</label>

					<label class="form-control w-full">
						<div class="label"><span class="label-text">{$t('suggestions.duration')}</span></div>
						<select class="select" bind:value={filters.duration}>
							<option value="">{$t('recomendations.any')}</option>
							{#each durations as duration}
								<option value={duration}>{duration}</option>
							{/each}
						</select>
					</label>
				{:else if selectedCategory === 'event'}
					<label class="form-control w-full">
						<div class="label"><span class="label-text">{$t('suggestions.event_type')}</span></div>
						<input class="input" type="text" bind:value={filters.event_type} />
					</label>

					<label class="form-control w-full">
						<div class="label">
							<span class="label-text">{$t('suggestions.time_preference')}</span>
						</div>
						<select class="select" bind:value={filters.time_preference}>
							<option value="">{$t('recomendations.any')}</option>
							{#each timePreferences as timePreference}
								<option value={timePreference}>{timePreference}</option>
							{/each}
						</select>
					</label>
				{:else if selectedCategory === 'lodging'}
					<label class="form-control w-full">
						<div class="label">
							<span class="label-text">{$t('suggestions.lodging_type')}</span>
						</div>
						<select class="select" bind:value={filters.lodging_type}>
							<option value="">{$t('recomendations.any')}</option>
							{#each lodgingTypes as lodgingType}
								<option value={lodgingType}>{lodgingType}</option>
							{/each}
						</select>
					</label>

					<div class="form-control w-full">
						<div class="label"><span class="label-text">{$t('suggestions.amenities')}</span></div>
						<div class="grid grid-cols-2 gap-2">
							{#each amenities as amenity}
								<label class="label cursor-pointer justify-start gap-2">
									<input
										type="checkbox"
										class="checkbox checkbox-sm"
										checked={Array.isArray(filters.amenities) &&
											filters.amenities.includes(amenity)}
										on:change={(event) => handleAmenityChange(amenity, event)}
									/>
									<span class="label-text capitalize">{amenity}</span>
								</label>
							{/each}
						</div>
					</div>
				{/if}
			{:else if isLoading}
				<div class="flex flex-col items-center justify-center py-12 gap-4">
					<span class="loading loading-spinner loading-lg text-primary"></span>
					<p class="opacity-80">{$t('suggestions.loading')}</p>
				</div>
			{:else if error}
				<div class="alert alert-error">
					<span>{error}</span>
				</div>
			{:else if suggestions.length === 0}
				<div class="alert alert-info">
					<span>{$t('suggestions.no_results')}</span>
				</div>
			{:else}
				<div class="space-y-3">
					{#each suggestions as suggestion}
						<div class="card bg-base-100 border border-base-300 shadow-sm">
							<div class="card-body p-4">
								<div class="flex items-start justify-between gap-3">
									<div>
										<h4 class="font-semibold text-base">{suggestion.name}</h4>
										{#if suggestion.description}
											<p class="text-sm opacity-80 mt-1">{suggestion.description}</p>
										{/if}
									</div>
								</div>

								{#if suggestion.why_fits}
									<div class="mt-2 p-3 rounded-lg bg-primary/10 border border-primary/20">
										<p class="text-xs uppercase tracking-wide opacity-70 mb-1">
											{$t('suggestions.why_fits')}
										</p>
										<p class="text-sm">{suggestion.why_fits}</p>
									</div>
								{/if}

								<div class="mt-3 flex flex-wrap gap-2 text-xs">
									{#if suggestion.location}
										<span class="badge badge-outline">📍 {suggestion.location}</span>
									{/if}
									{#if suggestion.rating !== null && suggestion.rating !== undefined && suggestion.rating !== ''}
										<span class="badge badge-outline">⭐ {suggestion.rating}</span>
									{/if}
									{#if suggestion.price_level}
										<span class="badge badge-outline">{suggestion.price_level}</span>
									{/if}
								</div>

								<div class="card-actions justify-end mt-3">
									<button
										type="button"
										class="btn btn-primary btn-sm"
										disabled={isAdding}
										on:click={() => handleAddSuggestion(suggestion)}
									>
										{#if isAdding && addingSuggestionName === suggestion.name}
											<span class="loading loading-spinner loading-xs"></span>
										{/if}
										{$t('suggestions.add_to_day')}
									</button>
								</div>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<div
			class="sticky bottom-0 bg-base-100/90 backdrop-blur-lg border-t border-base-300 -mx-6 -mb-6 px-4 py-3 mt-6"
		>
			<div class="flex justify-between gap-3">
				<button class="btn" type="button" on:click={close}>{$t('adventures.cancel')}</button>

				{#if step === 1}
					<div class="flex gap-2">
						<button class="btn btn-outline" type="button" on:click={() => (step = 0)}
							>{$t('adventures.back')}</button
						>
						<button class="btn btn-primary" type="button" on:click={fetchSuggestions}
							>{$t('suggestions.get_suggestions')}</button
						>
					</div>
				{:else if step === 2}
					<button
						class="btn btn-outline"
						type="button"
						on:click={goBackToFilters}
						disabled={isLoading || isAdding}
					>
						{$t('suggestions.try_again')}
					</button>
				{/if}
			</div>
		</div>
	</div>
	<form method="dialog" class="modal-backdrop">
		<button type="button" on:click={close}>close</button>
	</form>
</dialog>
