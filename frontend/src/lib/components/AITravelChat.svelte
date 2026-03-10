<script lang="ts">
	import { createEventDispatcher, onMount } from 'svelte';
	import { t } from 'svelte-i18n';
	import { mdiSend, mdiPlus, mdiDelete, mdiMenu, mdiClose } from '@mdi/js';
	import type { ChatProviderCatalogEntry, CollectionItineraryItem, Location } from '$lib/types.js';
	import { addToast } from '$lib/toasts';

	type ToolResultEntry = {
		tool_call_id?: string;
		name: string;
		result: unknown;
	};

	type ToolSummary = {
		icon: string;
		text: string;
	};

	type PlaceResult = {
		name: string;
		address?: string;
		rating?: number;
		latitude?: number | string;
		longitude?: number | string;
	};

	type Conversation = {
		id: string;
		title?: string;
	};

	type ChatMessage = {
		id: string;
		role: 'user' | 'assistant' | 'tool';
		content: string;
		name?: string;
		tool_calls?: Array<{ id?: string }>;
		tool_call_id?: string;
		tool_results?: ToolResultEntry[];
	};

	type ChatProviderCatalogConfiguredEntry = ChatProviderCatalogEntry & {
		instance_configured: boolean;
		user_configured: boolean;
	};

	type UserAISettingsResponse = {
		preferred_provider: string | null;
		preferred_model: string | null;
	};

	export let embedded = false;
	export let collectionId: string | undefined = undefined;
	export let collectionName: string | undefined = undefined;
	export let startDate: string | undefined = undefined;
	export let endDate: string | undefined = undefined;
	export let destination: string | undefined = undefined;

	let conversations: Conversation[] = [];
	let activeConversation: Conversation | null = null;
	let messages: ChatMessage[] = [];
	let inputMessage = '';
	let isStreaming = false;
	let sidebarOpen = !embedded;
	let streamingContent = '';

	let selectedProvider = '';
	let selectedModel = '';
	let availableModels: string[] = [];
	let modelsLoading = false;
	let chatProviders: ChatProviderCatalogConfiguredEntry[] = [];
	let providerError = '';
	let selectedProviderDefaultModel = '';
	let savedDefaultProvider = '';
	let savedDefaultModel = '';
	let initialDefaultsApplied = false;
	let loadedModelsForProvider = '';
	let showDateSelector = false;
	let selectedPlaceToAdd: PlaceResult | null = null;
	let selectedDate = '';
	let settingsOpen = false;
	let settingsDropdownRef: HTMLDetailsElement;

	const dispatch = createEventDispatcher<{
		close: void;
		itemAdded: { location: Location; itineraryItem: CollectionItineraryItem; date: string };
	}>();

	const MODEL_PREFS_STORAGE_KEY = 'voyage_chat_model_prefs';
	$: promptTripContext = collectionName || destination || '';

	onMount(() => {
		void initializeChat();

		const handleOutsideSettings = (event: Event) => {
			if (!settingsOpen || !settingsDropdownRef) {
				return;
			}

			const target = event.target as Node | null;
			if (target && !settingsDropdownRef.contains(target)) {
				settingsOpen = false;
			}
		};

		const handleSettingsEscape = (event: KeyboardEvent) => {
			if (event.key === 'Escape') {
				settingsOpen = false;
			}
		};

		const outsideEvents: Array<keyof DocumentEventMap> = ['pointerdown', 'mousedown', 'touchstart'];
		outsideEvents.forEach((eventName) => {
			document.addEventListener(eventName, handleOutsideSettings);
		});
		document.addEventListener('keydown', handleSettingsEscape);

		return () => {
			outsideEvents.forEach((eventName) => {
				document.removeEventListener(eventName, handleOutsideSettings);
			});
			document.removeEventListener('keydown', handleSettingsEscape);
		};
	});

	async function initializeChat(): Promise<void> {
		await Promise.all([loadConversations(), loadProviderCatalog(), loadUserAISettings()]);
		await applyInitialDefaults();
	}

	async function loadUserAISettings(): Promise<void> {
		try {
			const res = await fetch('/api/integrations/ai-settings/', {
				credentials: 'include'
			});
			if (!res.ok) {
				return;
			}

			const settings = (await res.json()) as UserAISettingsResponse[];
			const first = settings[0];
			if (!first) {
				return;
			}

			savedDefaultProvider = (first.preferred_provider || '').trim().toLowerCase();
			savedDefaultModel = (first.preferred_model || '').trim();
		} catch (e) {
			console.error('Failed to load AI settings:', e);
		}
	}

	async function applyInitialDefaults(): Promise<void> {
		if (initialDefaultsApplied || chatProviders.length === 0) {
			return;
		}

		if (
			savedDefaultProvider &&
			chatProviders.some((provider) => provider.id === savedDefaultProvider)
		) {
			selectedProvider = savedDefaultProvider;
		} else {
			const userConfigured = chatProviders.find((provider) => provider.user_configured);
			selectedProvider = (userConfigured || chatProviders[0]).id;
		}

		await loadModelsForProvider(selectedProvider);

		if (savedDefaultModel && selectedProvider === savedDefaultProvider) {
			selectedModel = availableModels.includes(savedDefaultModel)
				? savedDefaultModel
				: selectedProviderDefaultModel || availableModels[0] || '';
		} else {
			selectedModel = selectedProviderDefaultModel || availableModels[0] || '';
		}

		saveModelPref(selectedProvider, selectedModel);
		loadedModelsForProvider = selectedProvider;
		initialDefaultsApplied = true;
	}

	async function loadProviderCatalog(): Promise<void> {
		try {
			const res = await fetch('/api/chat/providers/', {
				credentials: 'include'
			});
			if (!res.ok) {
				providerError = 'Failed to load AI providers';
				return;
			}

			const data = await res.json();
			const providers = Array.isArray(data)
				? (data as ChatProviderCatalogConfiguredEntry[])
				: ((data.providers || []) as ChatProviderCatalogConfiguredEntry[]);

			const usable = providers.filter(
				(provider) =>
					provider.available_for_chat && (provider.user_configured || provider.instance_configured)
			);
			chatProviders = usable;

			if (usable.length > 0) {
				providerError = '';
				if (selectedProvider && !usable.some((provider) => provider.id === selectedProvider)) {
					selectedProvider = '';
				}
			} else {
				selectedProvider = '';
				availableModels = [];
				providerError = 'No AI providers configured. Add an API key in Settings.';
			}
		} catch (e) {
			console.error('Failed to load provider catalog:', e);
			providerError = 'Failed to load AI providers';
		}
	}

	async function loadModelsForProvider(providerId: string) {
		if (!providerId) {
			availableModels = [];
			return;
		}

		modelsLoading = true;
		try {
			const res = await fetch(`/api/chat/providers/${providerId}/models/`, {
				credentials: 'include'
			});
			const data = await res.json();

			if (data.models && data.models.length > 0) {
				availableModels = data.models;
			} else {
				availableModels = [];
			}
		} catch (e) {
			console.error('Failed to load models:', e);
			availableModels = [];
		} finally {
			modelsLoading = false;
		}
	}

	function saveModelPref(provider: string, model: string) {
		if (typeof window === 'undefined') {
			return;
		}

		try {
			const raw = window.localStorage.getItem(MODEL_PREFS_STORAGE_KEY);
			const prefs: Record<string, string> = raw ? JSON.parse(raw) : {};
			prefs[provider] = model;
			window.localStorage.setItem(MODEL_PREFS_STORAGE_KEY, JSON.stringify(prefs));
		} catch {
			// ignore localStorage persistence failures
		}
	}

	$: selectedProviderDefaultModel =
		chatProviders.find((provider) => provider.id === selectedProvider)?.default_model ?? '';

	$: if (
		selectedProvider &&
		initialDefaultsApplied &&
		loadedModelsForProvider !== selectedProvider
	) {
		loadedModelsForProvider = selectedProvider;
		void (async () => {
			await loadModelsForProvider(selectedProvider);
			if (!selectedModel || !availableModels.includes(selectedModel)) {
				selectedModel = selectedProviderDefaultModel || availableModels[0] || '';
			}
			saveModelPref(selectedProvider, selectedModel);
		})();
	}

	$: if (selectedProvider && initialDefaultsApplied) {
		saveModelPref(selectedProvider, selectedModel);
	}

	async function loadConversations() {
		const res = await fetch('/api/chat/conversations/');
		if (res.ok) {
			conversations = await res.json();
		}
	}

	async function createConversation(): Promise<Conversation | null> {
		const res = await fetch('/api/chat/conversations/', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({})
		});
		if (!res.ok) {
			return null;
		}

		const conv: Conversation = await res.json();
		conversations = [conv, ...conversations];
		activeConversation = conv;
		messages = [];
		return conv;
	}

	async function selectConversation(conv: Conversation) {
		activeConversation = conv;
		const res = await fetch(`/api/chat/conversations/${conv.id}/`);
		if (res.ok) {
			const data = await res.json();
			messages = rebuildConversationMessages(data.messages || []);
		}
	}

	function parseStoredToolResult(msg: ChatMessage): ToolResultEntry | null {
		if (msg.role !== 'tool') {
			return null;
		}

		try {
			return {
				tool_call_id: msg.tool_call_id,
				name: msg.name || 'tool',
				result: JSON.parse(msg.content)
			};
		} catch {
			return {
				tool_call_id: msg.tool_call_id,
				name: msg.name || 'tool',
				result: msg.content
			};
		}
	}

	function appendToolResultDedup(
		toolResults: ToolResultEntry[] | undefined,
		toolResult: ToolResultEntry
	): ToolResultEntry[] {
		const next = toolResults || [];
		if (
			toolResult.tool_call_id &&
			next.some((existing) => existing.tool_call_id === toolResult.tool_call_id)
		) {
			return next;
		}

		return [...next, toolResult];
	}

	function uniqueToolResultsByCallId(toolResults: ToolResultEntry[] | undefined): ToolResultEntry[] {
		if (!toolResults) {
			return [];
		}

		const seen = new Set<string>();
		const unique: ToolResultEntry[] = [];
		for (const result of toolResults) {
			if (result.tool_call_id) {
				if (seen.has(result.tool_call_id)) {
					continue;
				}
				seen.add(result.tool_call_id);
			}
			unique.push(result);
		}

		return unique;
	}

	function rebuildConversationMessages(rawMessages: ChatMessage[]): ChatMessage[] {
		const rebuilt = rawMessages.map((msg) => ({
			...msg,
			tool_results: undefined
		}));

		let activeAssistant: ChatMessage | null = null;

		for (const msg of rebuilt) {
			if (msg.role === 'assistant') {
				activeAssistant = Array.isArray(msg.tool_calls) && msg.tool_calls.length > 0 ? msg : null;
				continue;
			}

			if (msg.role !== 'tool' || !activeAssistant) {
				continue;
			}

			const toolCallIds = (activeAssistant.tool_calls || [])
				.map((toolCall) => toolCall?.id)
				.filter((toolCallId): toolCallId is string => !!toolCallId);

			if (msg.tool_call_id && toolCallIds.length > 0 && !toolCallIds.includes(msg.tool_call_id)) {
				continue;
			}

			const parsedResult = parseStoredToolResult(msg);
			if (!parsedResult) {
				continue;
			}

			activeAssistant.tool_results = appendToolResultDedup(
				activeAssistant.tool_results,
				parsedResult
			);

			if (
				toolCallIds.length > 0 &&
				(activeAssistant.tool_results?.length || 0) >= toolCallIds.length
			) {
				activeAssistant = null;
			}
		}

		return rebuilt;
	}

	async function deleteConversation(conv: Conversation) {
		await fetch(`/api/chat/conversations/${conv.id}/`, { method: 'DELETE' });
		conversations = conversations.filter((conversation) => conversation.id !== conv.id);
		if (activeConversation?.id === conv.id) {
			activeConversation = null;
			messages = [];
		}
	}

	async function sendMessage() {
		if (!inputMessage.trim() || isStreaming) return;
		if (!chatProviders.some((provider) => provider.id === selectedProvider)) return;

		let conversation = activeConversation;
		if (!conversation) {
			conversation = await createConversation();
			if (!conversation) return;
		}

		const userMsg: ChatMessage = { role: 'user', content: inputMessage, id: crypto.randomUUID() };
		messages = [...messages, userMsg];
		const msgText = inputMessage;
		inputMessage = '';
		isStreaming = true;
		streamingContent = '';

		const assistantMsg: ChatMessage = { role: 'assistant', content: '', id: crypto.randomUUID() };
		messages = [...messages, assistantMsg];

		try {
			const res = await fetch(`/api/chat/conversations/${conversation.id}/send_message/`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					message: msgText,
					provider: selectedProvider,
					model: selectedModel || undefined,
					collection_id: collectionId,
					collection_name: collectionName,
					start_date: startDate,
					end_date: endDate,
					destination
				})
			});

			if (!res.ok) {
				const err = await res.json();
				assistantMsg.content = err.error || $t('chat.connection_error');
				messages = [...messages];
				isStreaming = false;
				return;
			}

			const reader = res.body?.getReader();
			const decoder = new TextDecoder();
			let buffer = '';

			if (!reader) {
				isStreaming = false;
				return;
			}

			while (true) {
				const { done, value } = await reader.read();
				if (done) break;

				buffer += decoder.decode(value, { stream: true });
				const lines = buffer.split('\n');
				buffer = lines.pop() || '';

				for (const line of lines) {
					if (!line.startsWith('data: ')) continue;
					const data = line.slice(6).trim();
					if (!data || data === '[DONE]') continue;

					try {
						const parsed = JSON.parse(data);

						if (parsed.error) {
							assistantMsg.content = parsed.error;
							messages = [...messages];
							break;
						}

						if (parsed.content) {
							streamingContent += parsed.content;
							assistantMsg.content = streamingContent;
							messages = [...messages];
						}

						if (parsed.tool_result) {
							const toolResult: ToolResultEntry = {
								tool_call_id: parsed.tool_result.tool_call_id,
								name: parsed.tool_result.name || parsed.tool_result.tool || 'tool',
								result: parsed.tool_result.result
							};
							assistantMsg.tool_results = appendToolResultDedup(
								assistantMsg.tool_results,
								toolResult
							);
							messages = [...messages];
						}
					} catch {
						// ignore malformed chunks
					}
				}
			}

			loadConversations();
		} catch {
			assistantMsg.content = $t('chat.connection_error');
			messages = [...messages];
		} finally {
			isStreaming = false;
		}
	}

	async function sendPresetMessage(message: string) {
		if (isStreaming || chatProviders.length === 0) {
			return;
		}

		inputMessage = message;
		await sendMessage();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			sendMessage();
		}
	}

	function hasPlaceResults(result: ToolResultEntry): boolean {
		return (
			result.name === 'search_places' &&
			typeof result.result === 'object' &&
			result.result !== null &&
			Array.isArray((result.result as { results?: unknown[] }).results)
		);
	}

	function getPlaceResults(result: ToolResultEntry): any[] {
		if (!hasPlaceResults(result)) {
			return [];
		}

		return (result.result as { results: any[] }).results;
	}

	function hasWebSearchResults(result: ToolResultEntry): boolean {
		return (
			result.name === 'web_search' &&
			typeof result.result === 'object' &&
			result.result !== null &&
			Array.isArray((result.result as { results?: unknown[] }).results)
		);
	}

	function getWebSearchResults(result: ToolResultEntry): any[] {
		if (!hasWebSearchResults(result)) {
			return [];
		}

		return (result.result as { results: any[] }).results;
	}

	function parseCoordinate(value: unknown): number | null {
		if (typeof value === 'number' && Number.isFinite(value)) {
			return value;
		}

		if (typeof value === 'string') {
			const parsed = Number(value);
			return Number.isFinite(parsed) ? parsed : null;
		}

		return null;
	}

	function hasPlaceCoordinates(place: PlaceResult): boolean {
		return parseCoordinate(place.latitude) !== null && parseCoordinate(place.longitude) !== null;
	}

	function openDateSelector(place: PlaceResult) {
		selectedPlaceToAdd = place;
		selectedDate = startDate || '';
		showDateSelector = true;
	}

	function closeDateSelector() {
		showDateSelector = false;
		selectedPlaceToAdd = null;
		selectedDate = '';
	}

	async function addPlaceToItinerary(place: PlaceResult, date: string) {
		if (!collectionId || !date) {
			return;
		}

		const latitude = parseCoordinate(place.latitude);
		const longitude = parseCoordinate(place.longitude);
		if (latitude === null || longitude === null) {
			addToast('error', $t('chat.connection_error'));
			return;
		}

		try {
			const locationResponse = await fetch('/api/locations/', {
				method: 'POST',
				credentials: 'include',
				headers: {
					'Content-Type': 'application/json'
				},
				body: JSON.stringify({
					name: place.name,
					location: place.address || place.name,
					latitude,
					longitude,
					collections: [collectionId],
					is_public: false
				})
			});

			if (!locationResponse.ok) {
				throw new Error('Failed to create location');
			}

			const location = await locationResponse.json();

			const itineraryResponse = await fetch('/api/itineraries/', {
				method: 'POST',
				credentials: 'include',
				headers: {
					'Content-Type': 'application/json'
				},
				body: JSON.stringify({
					collection: collectionId,
					content_type: 'location',
					object_id: location.id,
					date,
					order: 0
				})
			});

			if (!itineraryResponse.ok) {
				throw new Error('Failed to add to itinerary');
			}

			const itineraryItem = await itineraryResponse.json();

			dispatch('itemAdded', { location, itineraryItem, date });
			addToast('success', $t('added_successfully'));
			closeDateSelector();
		} catch (error) {
			console.error('Failed to add to itinerary:', error);
			addToast('error', $t('chat.connection_error'));
		}
	}

	let messagesContainer: HTMLElement;
	$: visibleMessages = messages.filter((msg) => msg.role !== 'tool');
	$: lastVisibleMessageId = visibleMessages[visibleMessages.length - 1]?.id;
	$: if (messages && messagesContainer) {
		setTimeout(() => {
			messagesContainer?.scrollTo({ top: messagesContainer.scrollHeight, behavior: 'smooth' });
		}, 50);
	}

	function asRecord(value: unknown): Record<string, unknown> | null {
		if (!value || typeof value !== 'object' || Array.isArray(value)) {
			return null;
		}

		return value as Record<string, unknown>;
	}

	function getToolSummary(result: ToolResultEntry): ToolSummary {
		const payload = asRecord(result.result);
		const hasError = !!(payload && typeof payload.error === 'string' && payload.error.trim());

		if (hasError) {
			return {
				icon: '⚠️',
				text: `${result.name.replaceAll('_', ' ')} could not be completed.`
			};
		}

		if (result.name === 'list_trips') {
			const tripCount = Array.isArray(payload?.trips) ? payload.trips.length : 0;
			return {
				icon: '🧳',
				text:
					tripCount > 0
						? `Found ${tripCount} trip${tripCount === 1 ? '' : 's'}.`
						: 'No trips found.'
			};
		}

		if (result.name === 'get_trip_details') {
			const trip = asRecord(payload?.trip);
			const tripName = typeof trip?.name === 'string' ? trip.name : 'trip';
			const itineraryCount = Array.isArray(trip?.itinerary) ? trip.itinerary.length : 0;
			return {
				icon: '🗺️',
				text: `Loaded details for ${tripName} (${itineraryCount} itinerary item${itineraryCount === 1 ? '' : 's'}).`
			};
		}

		if (result.name === 'add_to_itinerary') {
			const location = asRecord(payload?.location);
			const locationName = typeof location?.name === 'string' ? location.name : 'location';
			return {
				icon: '📌',
				text: `Added ${locationName} to the itinerary.`
			};
		}

		if (result.name === 'get_weather') {
			const entries = Array.isArray(payload?.results) ? payload.results : [];
			const availableCount = entries.filter((entry) => asRecord(entry)?.available === true).length;
			return {
				icon: '🌤️',
				text: `Checked weather for ${entries.length} date${entries.length === 1 ? '' : 's'} (${availableCount} available).`
			};
		}

		return {
			icon: '🛠️',
			text: `${result.name.replaceAll('_', ' ')} completed.`
		};
	}
</script>

<div
	class="card"
	class:bg-base-200={!embedded}
	class:bg-base-100={embedded}
	class:shadow-xl={!embedded}
	class:border={embedded}
	class:border-base-300={embedded}
>
	<div class="card-body p-0">
		<div
			class="flex"
			class:h-[calc(100vh-64px)]={!embedded}
			class:h-[65vh]={embedded}
			class:min-h-[30rem]={embedded}
			class:max-h-[46rem]={embedded}
		>
			<div
				id="chat-conversations-sidebar"
				class="bg-base-200 flex flex-col border-r border-base-300 {embedded
					? 'w-60'
					: 'w-72'} {sidebarOpen ? '' : 'hidden'} lg:flex"
			>
				<div class="p-3 flex items-center justify-between border-b border-base-300">
					<h2 class="text-lg font-semibold">{$t('chat.conversations')}</h2>
					<button
						class="btn btn-sm btn-ghost"
						on:click={createConversation}
						title={$t('chat.new_conversation')}
					>
						<svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
							<path d={mdiPlus}></path>
						</svg>
					</button>
				</div>
				<div class="flex-1 overflow-y-auto">
					{#each conversations as conv}
						<div
							class="w-full p-3 hover:bg-base-300 flex items-center gap-2 {activeConversation?.id ===
							conv.id
								? 'bg-base-300'
								: ''}"
						>
							<button
								class="flex-1 text-left truncate text-sm"
								on:click={() => selectConversation(conv)}
							>
								{conv.title || $t('chat.untitled')}
							</button>
							<button
								class="btn btn-xs btn-ghost"
								on:click={() => deleteConversation(conv)}
								title={$t('chat.delete_conversation')}
							>
								<svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
									<path d={mdiDelete}></path>
								</svg>
							</button>
						</div>
					{/each}
					{#if conversations.length === 0}
						<p class="p-4 text-sm opacity-60">{$t('chat.no_conversations')}</p>
					{/if}
				</div>
			</div>

			<div class="flex-1 flex flex-col min-w-0">
				<div class="p-3 border-b border-base-300 flex items-center gap-3">
					<button
						class="btn btn-sm btn-ghost lg:hidden"
						on:click={() => (sidebarOpen = !sidebarOpen)}
						aria-controls="chat-conversations-sidebar"
						aria-expanded={sidebarOpen}
						aria-label={sidebarOpen
							? $t('chat_a11y.hide_conversations_aria')
							: $t('chat_a11y.show_conversations_aria')}
					>
						{#if sidebarOpen}
							<svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
								<path d={mdiClose}></path>
							</svg>
						{:else}
							<svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
								<path d={mdiMenu}></path>
							</svg>
						{/if}
					</button>
					<div class="flex items-center gap-2">
						<span class="text-2xl">✈️</span>
						<div>
							<h3 class="text-lg font-bold">
								{#if collectionName}
									{$t('travel_assistant')} · {collectionName}
								{:else}
									{$t('travel_assistant')}
								{/if}
							</h3>
						</div>
					</div>
					<div class="ml-auto flex items-center gap-2">
						<details
							class="dropdown dropdown-end"
							bind:open={settingsOpen}
							bind:this={settingsDropdownRef}
						>
							<summary
								class="btn btn-sm btn-ghost"
								aria-label={$t('chat_a11y.ai_settings_aria')}
								aria-expanded={settingsOpen}
							>
								⚙️
							</summary>
							<div
								class="dropdown-content z-20 mt-2 w-72 rounded-box border border-base-300 bg-base-100 p-3 shadow"
							>
								<div class="space-y-2">
									<label class="label py-0" for="chat-provider-select">
										<span class="label-text text-xs opacity-70">{$t('settings.provider')}</span>
									</label>
									<select
										id="chat-provider-select"
										class="select select-sm w-full"
										bind:value={selectedProvider}
										disabled={chatProviders.length === 0}
									>
										{#each chatProviders as provider}
											<option value={provider.id}>
												{provider.label}
												{#if provider.user_configured}
													✓{/if}
											</option>
										{/each}
									</select>
									<label class="label py-0" for="chat-model-select">
										<span class="label-text text-xs opacity-70">{$t('chat.model_label')}</span>
									</label>
									<select
										id="chat-model-select"
										class="select select-sm w-full"
										bind:value={selectedModel}
										disabled={chatProviders.length === 0}
									>
										{#if modelsLoading}
											<option value="">Loading...</option>
										{:else if availableModels.length === 0}
											<option value="">{$t('chat.model_placeholder')}</option>
										{:else}
											{#each availableModels as model}
												<option value={model}>{model}</option>
											{/each}
										{/if}
									</select>
								</div>
							</div>
						</details>
					</div>
				</div>

				{#if chatProviders.length === 0}
					<div class="p-4">
						<div class="alert alert-warning">
							<span
								>{providerError || 'No AI providers configured.'}
								<a href="/settings" class="link">Add an API key in Settings</a></span
							>
						</div>
					</div>
				{:else}
					<div class="flex-1 overflow-y-auto p-4 space-y-4" bind:this={messagesContainer}>
						{#if messages.length === 0 && !activeConversation}
							<div class="flex flex-col items-center justify-center h-full text-center">
								<div class="text-6xl opacity-40 mb-4">🌍</div>
								<h3 class="text-2xl font-bold mb-2">{$t('chat.welcome_title')}</h3>
								<p class="text-base-content/60 max-w-md">{$t('chat.welcome_message')}</p>
							</div>
						{:else}
							{#each visibleMessages as msg}
								<div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
									<div class="chat {msg.role === 'user' ? 'chat-end' : 'chat-start'}">
										<div
											class="chat-bubble {msg.role === 'user'
												? 'chat-bubble-primary'
												: 'chat-bubble-neutral'}"
										>
											<div class="whitespace-pre-wrap">{msg.content}</div>
											{#if msg.role === 'assistant' && msg.tool_results}
												<div class="mt-2 space-y-2">
													{#each uniqueToolResultsByCallId(msg.tool_results) as result}
														{#if hasPlaceResults(result)}
															<div class="grid gap-2">
																{#each getPlaceResults(result) as place}
																	<div class="card card-compact bg-base-200 p-3">
																		<h4 class="font-semibold">{place.name}</h4>
																		{#if place.address}
																			<p class="text-sm text-base-content/70">{place.address}</p>
																		{/if}
																		{#if place.rating}
																			<div class="flex items-center gap-1 text-sm">
																				<span>⭐</span>
																				<span>{place.rating}</span>
																			</div>
																		{/if}
																		{#if collectionId}
																			<button
																				class="btn btn-xs btn-primary btn-outline mt-2"
																				on:click={() => openDateSelector(place)}
																				disabled={!hasPlaceCoordinates(place)}
																			>
																				{$t('add_to_itinerary')}
																			</button>
																		{/if}
																	</div>
																{/each}
															</div>
														{:else if hasWebSearchResults(result)}
															<div class="grid gap-2">
																{#each getWebSearchResults(result) as item}
																	<a
																		href={item.url}
																		target="_blank"
																		rel="noopener noreferrer"
																		class="card card-compact bg-base-200 p-3 hover:bg-base-300 transition-colors block"
																	>
																		<h4 class="font-semibold link">{item.title}</h4>
																		<p class="text-sm text-base-content/70 line-clamp-2">
																			{item.snippet}
																		</p>
																	</a>
																{/each}
															</div>
														{:else}
															<div class="bg-base-200 rounded p-2 text-sm flex items-center gap-2">
																<span>{getToolSummary(result).icon}</span>
																<span>{getToolSummary(result).text}</span>
															</div>
														{/if}
													{/each}
												</div>
											{/if}
											{#if msg.role === 'assistant' && isStreaming && msg.id === lastVisibleMessageId}
												<div class="mt-2 inline-flex items-center gap-2 text-xs opacity-70">
													<span class="loading loading-dots loading-sm"></span>
													<span>{$t('processing')}</span>
												</div>
											{/if}
										</div>
									</div>
								</div>
							{/each}
						{/if}
					</div>

					<div class="border-t border-base-300 p-3 sm:p-4">
						<div class:mx-auto={!embedded} class:max-w-4xl={!embedded}>
							<div
								class="mb-3 flex gap-2"
								class:flex-wrap={!embedded}
								class:overflow-x-auto={embedded}
								class:pb-1={embedded}
							>
								{#if promptTripContext}
									<button
										class="btn btn-ghost"
										class:btn-xs={embedded}
										class:btn-sm={!embedded}
										class:whitespace-nowrap={embedded}
										on:click={() =>
											sendPresetMessage(
												`What are the best restaurants to include across my ${promptTripContext} itinerary?`
											)}
										disabled={isStreaming || chatProviders.length === 0}
									>
										🍽️ Restaurants
									</button>
									<button
										class="btn btn-ghost"
										class:btn-xs={embedded}
										class:btn-sm={!embedded}
										class:whitespace-nowrap={embedded}
										on:click={() =>
											sendPresetMessage(
												`What activities should I plan across my ${promptTripContext} itinerary?`
											)}
										disabled={isStreaming || chatProviders.length === 0}
									>
										🎯 Activities
									</button>
								{/if}
								{#if startDate && endDate}
									<button
										class="btn btn-ghost"
										class:btn-xs={embedded}
										class:btn-sm={!embedded}
										class:whitespace-nowrap={embedded}
										on:click={() =>
											sendPresetMessage(
												`What should I pack for my trip from ${startDate} to ${endDate}?`
											)}
										disabled={isStreaming || chatProviders.length === 0}
									>
										🎒 Packing tips
									</button>
								{/if}
								<button
									class="btn btn-ghost"
									class:btn-xs={embedded}
									class:btn-sm={!embedded}
									class:whitespace-nowrap={embedded}
									on:click={() =>
										sendPresetMessage('Can you help me plan a day-by-day itinerary for this trip?')}
									disabled={isStreaming || chatProviders.length === 0}
								>
									📅 Itinerary help
								</button>
							</div>
						</div>
						<div class="flex items-end gap-2" class:mx-auto={!embedded} class:max-w-4xl={!embedded}>
							<textarea
								class="textarea flex-1 resize-none"
								placeholder={$t('chat.input_placeholder')}
								bind:value={inputMessage}
								on:keydown={handleKeydown}
								rows="1"
								disabled={isStreaming}
							></textarea>
							<button
								class="btn btn-primary self-end"
								on:click={sendMessage}
								disabled={isStreaming || !inputMessage.trim() || chatProviders.length === 0}
								title={$t('chat.send')}
							>
								{#if isStreaming}
									<span class="loading loading-spinner loading-sm"></span>
								{:else}
									<svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
										<path d={mdiSend}></path>
									</svg>
								{/if}
							</button>
						</div>
					</div>
				{/if}
			</div>
		</div>
	</div>
</div>

{#if showDateSelector && selectedPlaceToAdd}
	<div class="modal modal-open">
		<div class="modal-box">
			<h3 class="font-bold text-lg">{$t('add_to_itinerary')}</h3>
			<p class="py-4">
				{$t('add_to_which_day', { values: { placeName: selectedPlaceToAdd.name } })}
			</p>

			<input
				type="date"
				class="input w-full"
				bind:value={selectedDate}
				min={startDate}
				max={endDate}
			/>

			<div class="modal-action">
				<button class="btn btn-ghost" on:click={closeDateSelector}>{$t('adventures.cancel')}</button
				>
				<button
					class="btn btn-primary"
					on:click={() =>
						selectedPlaceToAdd && addPlaceToItinerary(selectedPlaceToAdd, selectedDate)}
					disabled={!selectedDate}
				>
					{$t('adventures.add')}
				</button>
			</div>
		</div>
	</div>
{/if}
