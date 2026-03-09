<script lang="ts">
	import { createEventDispatcher, onMount } from 'svelte';
	import { t } from 'svelte-i18n';
	import { mdiSend, mdiPlus, mdiDelete, mdiMenu, mdiClose } from '@mdi/js';
	import type { ChatProviderCatalogEntry } from '$lib/types.js';
	import { addToast } from '$lib/toasts';

	type ToolResultEntry = {
		name: string;
		result: unknown;
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
		tool_results?: ToolResultEntry[];
	};

	type ChatProviderCatalogConfiguredEntry = ChatProviderCatalogEntry & {
		instance_configured: boolean;
		user_configured: boolean;
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
	let sidebarOpen = true;
	let streamingContent = '';

	let selectedProvider = '';
	let selectedModel = '';
	let availableModels: string[] = [];
	let modelsLoading = false;
	let chatProviders: ChatProviderCatalogConfiguredEntry[] = [];
	let providerError = '';
	let selectedProviderDefaultModel = '';
	let showDateSelector = false;
	let selectedPlaceToAdd: PlaceResult | null = null;
	let selectedDate = '';

	const dispatch = createEventDispatcher<{
		close: void;
		itemAdded: { locationId: string; date: string };
	}>();

	const MODEL_PREFS_STORAGE_KEY = 'voyage_chat_model_prefs';
	let initializedModelProvider = '';

	onMount(async () => {
		await Promise.all([loadConversations(), loadProviderCatalog()]);
	});

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
				if (!selectedProvider || !usable.some((provider) => provider.id === selectedProvider)) {
					const userConfigured = usable.find((provider) => provider.user_configured);
					selectedProvider = (userConfigured || usable[0]).id;
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

	async function loadModelsForProvider() {
		if (!selectedProvider) {
			availableModels = [];
			return;
		}

		modelsLoading = true;
		try {
			const res = await fetch(`/api/chat/providers/${selectedProvider}/models/`, {
				credentials: 'include'
			});
			const data = await res.json();

			if (data.models && data.models.length > 0) {
				availableModels = data.models;
				if (!selectedModel || !availableModels.includes(selectedModel)) {
					selectedModel = availableModels[0];
				}
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

	function loadModelPref(provider: string): string {
		if (typeof window === 'undefined') {
			return '';
		}

		try {
			const raw = window.localStorage.getItem(MODEL_PREFS_STORAGE_KEY);
			if (!raw) {
				return '';
			}

			const prefs = JSON.parse(raw) as Record<string, string>;
			const value = prefs[provider];
			return typeof value === 'string' ? value : '';
		} catch {
			return '';
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

	$: if (selectedProvider && initializedModelProvider !== selectedProvider) {
		selectedModel = loadModelPref(selectedProvider) || selectedProviderDefaultModel || '';
		initializedModelProvider = selectedProvider;
	}

	$: if (selectedProvider && initializedModelProvider === selectedProvider) {
		saveModelPref(selectedProvider, selectedModel);
	}

	$: selectedProviderDefaultModel =
		chatProviders.find((provider) => provider.id === selectedProvider)?.default_model ?? '';

	$: if (selectedProvider) {
		void loadModelsForProvider();
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
			messages = data.messages || [];
		}
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
								name: parsed.tool_result.name || parsed.tool_result.tool || 'tool',
								result: parsed.tool_result.result
							};
							assistantMsg.tool_results = [...(assistantMsg.tool_results || []), toolResult];
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

	function parseToolResults(msg: ChatMessage): ToolResultEntry[] {
		if (msg.tool_results?.length) {
			return msg.tool_results;
		}

		if (msg.role !== 'tool') {
			return [];
		}

		try {
			return [{ name: msg.name || 'tool', result: JSON.parse(msg.content) }];
		} catch {
			return [{ name: msg.name || 'tool', result: msg.content }];
		}
	}

	function hasPlaceResults(result: ToolResultEntry): boolean {
		return (
			result.name === 'search_places' &&
			typeof result.result === 'object' &&
			result.result !== null &&
			Array.isArray((result.result as { places?: unknown[] }).places)
		);
	}

	function getPlaceResults(result: ToolResultEntry): any[] {
		if (!hasPlaceResults(result)) {
			return [];
		}

		return (result.result as { places: any[] }).places;
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

			dispatch('itemAdded', { locationId: location.id, date });
			addToast('success', $t('added_successfully'));
			closeDateSelector();
		} catch (error) {
			console.error('Failed to add to itinerary:', error);
			addToast('error', $t('chat.connection_error'));
		}
	}

	let messagesContainer: HTMLElement;
	$: if (messages && messagesContainer) {
		setTimeout(() => {
			messagesContainer?.scrollTo({ top: messagesContainer.scrollHeight, behavior: 'smooth' });
		}, 50);
	}
</script>

<div class="card bg-base-200 shadow-xl">
	<div class="card-body p-0">
		<div class="flex" class:h-[calc(100vh-64px)]={!embedded} class:h-[70vh]={embedded}>
			<div
				class="w-72 bg-base-200 flex flex-col border-r border-base-300 {sidebarOpen
					? ''
					: 'hidden'} lg:flex"
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
						<select
							class="select select-bordered select-sm"
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
						<select
							class="select select-bordered select-sm"
							bind:value={selectedModel}
							disabled={chatProviders.length === 0}
						>
							{#if modelsLoading}
								<option value="">Loading...</option>
							{:else if availableModels.length === 0}
								<option value="">Default</option>
							{:else}
								{#each availableModels as model}
									<option value={model}>{model}</option>
								{/each}
							{/if}
						</select>
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
							{#each messages as msg}
								<div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
									{#if msg.role === 'tool'}
										<div class="max-w-2xl w-full">
											<div class="bg-base-200 rounded-lg p-3 text-xs space-y-2">
												<div class="font-semibold mb-1 text-primary">🗺️ {msg.name}</div>
												{#each parseToolResults(msg) as result}
													{#if hasPlaceResults(result)}
														<div class="grid gap-2">
															{#each getPlaceResults(result) as place}
																<div class="card card-compact bg-base-100 p-3">
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
																	class="card card-compact bg-base-100 p-3 hover:bg-base-300 transition-colors block"
																>
																	<h4 class="font-semibold link">{item.title}</h4>
																	<p class="text-sm text-base-content/70 line-clamp-2">
																		{item.snippet}
																	</p>
																</a>
															{/each}
														</div>
													{:else}
														<div class="bg-base-100 rounded p-2 text-sm">
															<pre>{JSON.stringify(result.result, null, 2)}</pre>
														</div>
													{/if}
												{/each}
											</div>
										</div>
									{:else}
										<div class="chat {msg.role === 'user' ? 'chat-end' : 'chat-start'}">
											<div
												class="chat-bubble {msg.role === 'user'
													? 'chat-bubble-primary'
													: 'chat-bubble-neutral'}"
											>
												<div class="whitespace-pre-wrap">{msg.content}</div>
												{#if msg.role === 'assistant' && msg.tool_results}
													<div class="mt-2 space-y-2">
														{#each msg.tool_results as result}
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
																<div class="bg-base-200 rounded p-2 text-sm">
																	<pre>{JSON.stringify(result.result, null, 2)}</pre>
																</div>
															{/if}
														{/each}
													</div>
												{/if}
												{#if msg.role === 'assistant' && isStreaming && msg.id === messages[messages.length - 1]?.id && !msg.content}
													<span class="loading loading-dots loading-sm"></span>
												{/if}
											</div>
										</div>
									{/if}
								</div>
							{/each}
						{/if}
					</div>

					<div class="p-4 border-t border-base-300">
						<div class="max-w-4xl mx-auto">
							<div class="flex flex-wrap gap-2 mb-3">
								{#if destination}
									<button
										class="btn btn-sm btn-ghost"
										on:click={() =>
											sendPresetMessage(`What are the best restaurants in ${destination}?`)}
										disabled={isStreaming || chatProviders.length === 0}
									>
										🍽️ Restaurants
									</button>
									<button
										class="btn btn-sm btn-ghost"
										on:click={() =>
											sendPresetMessage(`What activities can I do in ${destination}?`)}
										disabled={isStreaming || chatProviders.length === 0}
									>
										🎯 Activities
									</button>
								{/if}
								{#if startDate && endDate}
									<button
										class="btn btn-sm btn-ghost"
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
									class="btn btn-sm btn-ghost"
									on:click={() =>
										sendPresetMessage('Can you help me plan a day-by-day itinerary for this trip?')}
									disabled={isStreaming || chatProviders.length === 0}
								>
									📅 Itinerary help
								</button>
							</div>
						</div>
						<div class="flex gap-2 max-w-4xl mx-auto">
							<textarea
								class="textarea textarea-bordered flex-1 resize-none"
								placeholder={$t('chat.input_placeholder')}
								bind:value={inputMessage}
								on:keydown={handleKeydown}
								rows="1"
								disabled={isStreaming}
							></textarea>
							<button
								class="btn btn-primary"
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
				class="input input-bordered w-full"
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
