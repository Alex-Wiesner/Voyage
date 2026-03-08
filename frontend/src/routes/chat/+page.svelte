<script lang="ts">
	import { onMount } from 'svelte';
	import { t } from 'svelte-i18n';
	import { mdiRobot, mdiSend, mdiPlus, mdiDelete, mdiMenu, mdiClose } from '@mdi/js';

	type Provider = {
		value: string;
		label: string;
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
	};

	let conversations: Conversation[] = [];
	let activeConversation: Conversation | null = null;
	let messages: ChatMessage[] = [];
	let inputMessage = '';
	let isStreaming = false;
	let sidebarOpen = true;
	let streamingContent = '';

	let selectedProvider = 'openai';
	const providers: Provider[] = [
		{ value: 'openai', label: 'OpenAI' },
		{ value: 'anthropic', label: 'Anthropic' },
		{ value: 'gemini', label: 'Google Gemini' },
		{ value: 'ollama', label: 'Ollama' },
		{ value: 'groq', label: 'Groq' },
		{ value: 'mistral', label: 'Mistral' },
		{ value: 'github_models', label: 'GitHub Models' },
		{ value: 'openrouter', label: 'OpenRouter' }
	];

	onMount(loadConversations);

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
				body: JSON.stringify({ message: msgText, provider: selectedProvider })
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
							const toolMsg: ChatMessage = {
								role: 'tool',
								content: JSON.stringify(parsed.tool_result, null, 2),
								name: parsed.tool_result.tool || 'tool',
								id: crypto.randomUUID()
							};

							const idx = messages.findIndex((m) => m.id === assistantMsg.id);
							messages = [...messages.slice(0, idx), toolMsg, ...messages.slice(idx)];

							streamingContent = '';
							assistantMsg.content = '';
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

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			sendMessage();
		}
	}

	let messagesContainer: HTMLElement;
	$: if (messages && messagesContainer) {
		setTimeout(() => {
			messagesContainer?.scrollTo({ top: messagesContainer.scrollHeight, behavior: 'smooth' });
		}, 50);
	}
</script>

<svelte:head>
	<title>{$t('chat.title')} | Voyage</title>
</svelte:head>

<div class="flex h-[calc(100vh-64px)]">
	<div class="w-72 bg-base-200 flex flex-col border-r border-base-300 {sidebarOpen ? '' : 'hidden'} lg:flex">
		<div class="p-3 flex items-center justify-between border-b border-base-300">
			<h2 class="text-lg font-semibold">{$t('chat.conversations')}</h2>
			<button class="btn btn-sm btn-ghost" on:click={createConversation} title={$t('chat.new_conversation')}>
				<svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
					<path d={mdiPlus}></path>
				</svg>
			</button>
		</div>
		<div class="flex-1 overflow-y-auto">
			{#each conversations as conv}
				<div
					class="w-full p-3 hover:bg-base-300 flex items-center gap-2 {activeConversation?.id === conv.id
						? 'bg-base-300'
						: ''}"
				>
					<button class="flex-1 text-left truncate text-sm" on:click={() => selectConversation(conv)}>
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

	<div class="flex-1 flex flex-col">
		<div class="p-3 border-b border-base-300 flex items-center gap-3">
			<button class="btn btn-sm btn-ghost lg:hidden" on:click={() => (sidebarOpen = !sidebarOpen)}>
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
			<svg class="w-6 h-6 text-primary" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
				<path d={mdiRobot}></path>
			</svg>
			<h1 class="text-lg font-semibold">{$t('chat.title')}</h1>
			<div class="ml-auto">
				<select class="select select-bordered select-sm" bind:value={selectedProvider}>
					{#each providers as provider}
						<option value={provider.value}>{provider.label}</option>
					{/each}
				</select>
			</div>
		</div>

		<div class="flex-1 overflow-y-auto p-4 space-y-4" bind:this={messagesContainer}>
			{#if messages.length === 0 && !activeConversation}
				<div class="flex flex-col items-center justify-center h-full text-center">
					<svg
						class="w-16 h-16 text-primary opacity-40 mb-4"
						viewBox="0 0 24 24"
						fill="currentColor"
						aria-hidden="true"
					>
						<path d={mdiRobot}></path>
					</svg>
					<h2 class="text-2xl font-bold mb-2">{$t('chat.welcome_title')}</h2>
					<p class="text-base-content/60 max-w-md">{$t('chat.welcome_message')}</p>
				</div>
			{:else}
				{#each messages as msg}
					<div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
						{#if msg.role === 'tool'}
							<div class="max-w-2xl w-full">
								<div class="bg-base-200 rounded-lg p-3 text-xs">
									<div class="font-semibold mb-1 text-primary">🔧 {msg.name}</div>
									<pre class="whitespace-pre-wrap overflow-x-auto">{msg.content}</pre>
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
									{#if msg.role === 'assistant' &&
									isStreaming &&
									msg.id === messages[messages.length - 1]?.id &&
									!msg.content}
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
					disabled={isStreaming || !inputMessage.trim()}
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
	</div>
</div>
