<script lang="ts">
	import { createEventDispatcher } from 'svelte';

	import FileDocumentEdit from '~icons/mdi/file-document-edit';
	import ArchiveArrowDown from '~icons/mdi/archive-arrow-down';
	import ArchiveArrowUp from '~icons/mdi/archive-arrow-up';
	import ShareVariant from '~icons/mdi/share-variant';

	import { goto } from '$app/navigation';
	import type { Location, Collection, User, SlimCollection, ContentImage } from '$lib/types';
	import { addToast } from '$lib/toasts';
	import { t } from 'svelte-i18n';
	import { copyToClipboard } from '$lib/index';

	import Plus from '~icons/mdi/plus';
	import Minus from '~icons/mdi/minus';
	import DotsHorizontal from '~icons/mdi/dots-horizontal';
	import TrashCan from '~icons/mdi/trashcan';
	import DeleteWarning from '../DeleteWarning.svelte';
	import ShareModal from '../ShareModal.svelte';
	import CardCarousel from '../CardCarousel.svelte';
	import ExitRun from '~icons/mdi/exit-run';
	import Eye from '~icons/mdi/eye';
	import EyeOff from '~icons/mdi/eye-off';
	import Check from '~icons/mdi/check';
	import LinkIcon from '~icons/mdi/link';
	import DownloadIcon from '~icons/mdi/download';
	import ContentCopy from '~icons/mdi/content-copy';

	const dispatch = createEventDispatcher();

	export let type: String | undefined | null;
	export let linkedCollectionList: string[] | null = null;
	export let user: User | null;
	let isShareModalOpen: boolean = false;
	let copied: boolean = false;

	async function copyLink() {
		try {
			const url = `${location.origin}/collections/${collection.id}`;
			await copyToClipboard(url);
			copied = true;
			setTimeout(() => (copied = false), 2000);
		} catch (e) {
			addToast('error', $t('adventures.copy_failed') || 'Copy failed');
		}
	}

	let isDuplicating = false;

	async function duplicateCollection() {
		if (isDuplicating) return;
		isDuplicating = true;
		try {
			const res = await fetch(`/api/collections/${collection.id}/duplicate/`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' }
			});
			if (res.ok) {
				const newCollection = await res.json();
				addToast('success', $t('adventures.collection_duplicate_success'));
				dispatch('duplicate', newCollection);
			} else {
				addToast('error', $t('adventures.collection_duplicate_error'));
			}
		} catch (e) {
			addToast('error', $t('adventures.collection_duplicate_error'));
		} finally {
			isDuplicating = false;
		}
	}

	function editAdventure() {
		dispatch('edit', collection);
	}

	async function exportCollectionZip() {
		try {
			const res = await fetch(`/api/collections/${collection.id}/export`);
			if (!res.ok) {
				addToast('error', $t('adventures.export_failed') || 'Export failed');
				return;
			}
			const blob = await res.blob();
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = `collection-${String(collection.name).replace(/\s+/g, '_')}.zip`;
			a.click();
			URL.revokeObjectURL(url);
			addToast('success', $t('adventures.export_success') || 'Exported collection');
		} catch (e) {
			addToast('error', $t('adventures.export_failed') || 'Export failed');
		}
	}

	async function archiveCollection(is_archived: boolean) {
		let res = await fetch(`/api/collections/${collection.id}/`, {
			method: 'PATCH',
			headers: {
				'Content-Type': 'application/json'
			},
			body: JSON.stringify({ is_archived: is_archived })
		});
		if (res.ok) {
			if (is_archived) {
				addToast('info', $t('adventures.archived_collection_message'));
				dispatch('archive', collection.id);
			} else {
				addToast('info', $t('adventures.unarchived_collection_message'));
				dispatch('unarchive', collection.id);
			}
		} else {
			console.log('Error archiving collection');
		}
	}

	export let collection: Collection | SlimCollection;

	let location_images: ContentImage[] = [];
	$: {
		let images: ContentImage[] = [];
		if ('location_images' in collection) {
			images = collection.location_images;
		} else {
			images = collection.locations.flatMap((location: Location) => location.images);
		}

		const primaryImage = 'primary_image' in collection ? collection.primary_image : null;
		if (primaryImage) {
			const coverImage = { ...primaryImage, is_primary: true };
			const remainingImages = images
				.filter((img) => img.id !== primaryImage.id)
				.map((img) => ({ ...img, is_primary: false }));
			location_images = [coverImage, ...remainingImages];
		} else {
			location_images = images;
		}
	}

	let locationLength: number = 0;
	$: locationLength =
		'location_count' in collection ? collection.location_count : collection.locations.length;

	function formatCollectionDate(dateString: string) {
		return new Date(dateString).toLocaleDateString('en-GB', {
			timeZone: 'UTC',
			month: 'short',
			day: 'numeric',
			year: 'numeric'
		});
	}

	$: dateRangeString =
		collection.start_date && collection.end_date
			? `${formatCollectionDate(collection.start_date)} – ${formatCollectionDate(collection.end_date)}`
			: collection.start_date
				? formatCollectionDate(collection.start_date)
				: collection.end_date
					? formatCollectionDate(collection.end_date)
					: '';

	$: days =
		collection.start_date && collection.end_date
			? Math.floor(
					(new Date(collection.end_date).getTime() - new Date(collection.start_date).getTime()) /
						(1000 * 60 * 60 * 24)
				) + 1
			: null;

	function goToCollection() {
		goto(`/collections/${collection.id}`);
	}

	function handleCardKeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			goToCollection();
		}
	}

	async function deleteCollection() {
		let res = await fetch(`/api/collections/${collection.id}`, {
			method: 'DELETE'
		});
		if (res.ok) {
			addToast('info', $t('adventures.delete_collection_success'));
			dispatch('delete', collection.id);
		} else {
			console.log('Error deleting collection');
		}
	}

	let isWarningModalOpen: boolean = false;
</script>

{#if isWarningModalOpen}
	<DeleteWarning
		title={$t('adventures.delete_collection')}
		button_text={$t('adventures.delete')}
		description={$t('adventures.delete_collection_warning')}
		is_warning={true}
		on:close={() => (isWarningModalOpen = false)}
		on:confirm={deleteCollection}
	/>
{/if}

{#if isShareModalOpen}
	<ShareModal {collection} on:close={() => (isShareModalOpen = false)} />
{/if}

<div
	class="bg-base-100 rounded-2xl shadow hover:shadow-xl transition-all overflow-hidden w-full cursor-pointer group"
	role="link"
	aria-label={collection.name}
	tabindex="0"
	on:click={goToCollection}
	on:keydown={handleCardKeydown}
>
	<div class="relative h-56 overflow-hidden card-carousel-tall">
		<CardCarousel images={location_images} name={collection.name} icon="📚" />
		<div
			class="absolute inset-0 bg-gradient-to-t from-black/70 via-black/20 to-transparent pointer-events-none z-10"
		></div>

		<div class="absolute top-3 left-3 z-20 flex gap-1.5">
			{#if collection.status === 'folder'}
				<div
					class="flex items-center gap-1 bg-black/40 backdrop-blur-sm text-white rounded-full px-2.5 py-1 text-xs font-medium"
				>
					📁 {$t('adventures.folder')}
				</div>
			{:else if collection.status === 'upcoming'}
				<div
					class="flex items-center gap-1 bg-black/40 backdrop-blur-sm text-white rounded-full px-2.5 py-1 text-xs font-medium"
				>
					🚀 {$t('adventures.upcoming')}
				</div>
				{#if collection.days_until_start !== null}
					<div
						class="flex items-center gap-1 bg-black/40 backdrop-blur-sm text-white rounded-full px-2.5 py-1 text-xs font-medium"
					>
						⏳ {collection.days_until_start}
						{collection.days_until_start === 1 ? $t('adventures.day') : $t('adventures.days')}
					</div>
				{/if}
			{:else if collection.status === 'in_progress'}
				<div
					class="flex items-center gap-1 bg-black/40 backdrop-blur-sm text-white rounded-full px-2.5 py-1 text-xs font-medium"
				>
					🎯 {$t('adventures.in_progress')}
				</div>
			{:else if collection.status === 'completed'}
				<div
					class="flex items-center gap-1 bg-black/40 backdrop-blur-sm text-white rounded-full px-2.5 py-1 text-xs font-medium"
				>
					<Check class="w-3.5 h-3.5" />
					{$t('adventures.completed')}
				</div>
			{/if}
			{#if collection.is_archived}
				<div
					class="flex items-center gap-1 bg-black/40 backdrop-blur-sm text-white rounded-full px-2.5 py-1 text-xs font-medium"
				>
					{$t('adventures.archived')}
				</div>
			{/if}
		</div>

		<div class="absolute top-3 right-3 z-20 flex items-center gap-1.5">
			<div
				class="tooltip tooltip-left"
				data-tip={collection.is_public ? $t('adventures.public') : $t('adventures.private')}
			>
				<div
					class="flex items-center justify-center bg-black/40 backdrop-blur-sm text-white rounded-full w-7 h-7"
					aria-label={collection.is_public ? $t('adventures.public') : $t('adventures.private')}
				>
					{#if collection.is_public}
						<Eye class="w-4 h-4" />
					{:else}
						<EyeOff class="w-4 h-4" />
					{/if}
				</div>
			</div>

			{#if user && user.uuid == collection.user && type != 'link' && type != 'viewonly'}
				<div class="dropdown dropdown-end">
					<button
						type="button"
						class="btn btn-ghost bg-black/40 backdrop-blur-sm text-white rounded-full w-7 h-7 p-0 min-h-0 border-0 hover:bg-black/55"
						on:click|stopPropagation
					>
						<DotsHorizontal class="w-4 h-4" />
					</button>
					<ul
						class="dropdown-content menu bg-base-100 rounded-box z-[1] w-64 p-2 shadow-xl border border-base-300 mt-1"
					>
						{#if type != 'viewonly'}
							<li>
								<button class="flex items-center gap-2" on:click|stopPropagation={editAdventure}>
									<FileDocumentEdit class="w-4 h-4" />
									{$t('adventures.edit_collection')}
								</button>
							</li>
							<li>
								<button
									class="flex items-center gap-2"
									on:click|stopPropagation={() => (isShareModalOpen = true)}
								>
									<ShareVariant class="w-4 h-4" />
									{$t('adventures.share')}
								</button>
							</li>
							{#if collection.is_public}
								<li>
									<button on:click|stopPropagation={copyLink} class="flex items-center gap-2">
										{#if copied}
											<Check class="w-4 h-4 text-success" />
											<span>{$t('adventures.link_copied')}</span>
										{:else}
											<LinkIcon class="w-4 h-4" />
											{$t('adventures.copy_link')}
										{/if}
									</button>
								</li>
							{/if}
							{#if collection.is_archived}
								<li>
									<button
										class="flex items-center gap-2"
										on:click|stopPropagation={() => archiveCollection(false)}
									>
										<ArchiveArrowUp class="w-4 h-4" />
										{$t('adventures.unarchive')}
									</button>
								</li>
							{:else}
								<li>
									<button
										class="flex items-center gap-2"
										on:click|stopPropagation={() => archiveCollection(true)}
									>
										<ArchiveArrowDown class="w-4 h-4" />
										{$t('adventures.archive')}
									</button>
								</li>
							{/if}
							<li>
								<button
									class="flex items-center gap-2"
									on:click|stopPropagation={exportCollectionZip}
								>
									<DownloadIcon class="w-4 h-4" />
									{$t('adventures.export_zip')}
								</button>
							</li>
							<li>
								<button
									class="flex items-center gap-2"
									on:click|stopPropagation={duplicateCollection}
									disabled={isDuplicating}
								>
									<ContentCopy class="w-4 h-4" />
									{isDuplicating ? '...' : $t('adventures.duplicate')}
								</button>
							</li>
							<div class="divider my-1"></div>
							<li>
								<button
									id="delete_collection"
									data-umami-event="Delete Collection"
									class="text-error flex items-center gap-2"
									on:click|stopPropagation={() => (isWarningModalOpen = true)}
								>
									<TrashCan class="w-4 h-4" />
									{$t('adventures.delete')}
								</button>
							</li>
						{/if}
					</ul>
				</div>
			{:else if user && collection.shared_with && collection.shared_with.includes(user.uuid) && type != 'link'}
				<div class="dropdown dropdown-end">
					<button
						type="button"
						class="btn btn-ghost bg-black/40 backdrop-blur-sm text-white rounded-full w-7 h-7 p-0 min-h-0 border-0 hover:bg-black/55"
						on:click|stopPropagation
					>
						<DotsHorizontal class="w-4 h-4" />
					</button>
					<ul
						class="dropdown-content menu bg-base-100 rounded-box z-[1] w-64 p-2 shadow-xl border border-base-300 mt-1"
					>
						<li>
							<button
								class="text-error flex items-center gap-2"
								on:click|stopPropagation={() => dispatch('leave', collection.id)}
							>
								<ExitRun class="w-4 h-4" />
								{$t('adventures.leave_collection')}
							</button>
						</li>
					</ul>
				</div>
			{/if}
		</div>

		<div class="absolute bottom-0 left-0 right-0 p-4 z-20 pointer-events-none">
			<h3 class="text-white font-bold text-base leading-snug line-clamp-2 drop-shadow-sm">
				{collection.name}
			</h3>
			{#if collection.start_date || collection.end_date}
				<p class="text-white/75 text-xs mt-0.5 drop-shadow-sm">{dateRangeString}</p>
			{/if}
		</div>

		{#if type == 'link'}
			<div class="absolute bottom-3 right-3 z-20">
				{#if linkedCollectionList && linkedCollectionList
						.map(String)
						.includes(String(collection.id))}
					<button
						class="btn btn-xs border-0 bg-black/40 backdrop-blur-sm text-white rounded-full px-3 hover:bg-black/55"
						on:click|stopPropagation={() => dispatch('unlink', collection.id)}
					>
						<Minus class="w-3.5 h-3.5" />
						{$t('adventures.remove_from_collection')}
					</button>
				{:else}
					<button
						class="btn btn-xs border-0 bg-black/40 backdrop-blur-sm text-white rounded-full px-3 hover:bg-black/55"
						on:click|stopPropagation={() => dispatch('link', collection.id)}
					>
						<Plus class="w-3.5 h-3.5" />
						{$t('adventures.add_to_collection')}
					</button>
				{/if}
			</div>
		{/if}
	</div>

	<div class="px-4 py-3 flex items-center gap-3 text-sm text-base-content/60">
		<span
			>{locationLength}
			{locationLength !== 1 ? $t('locations.locations') : $t('locations.location')}</span
		>
		{#if days}
			<span>· {days} {days !== 1 ? $t('adventures.days') : $t('adventures.day')}</span>
		{/if}
	</div>
</div>

<style>
	.line-clamp-2 {
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	.card-carousel-tall :global(figure),
	.card-carousel-tall :global(.carousel),
	.card-carousel-tall :global(.carousel-item),
	.card-carousel-tall :global(img),
	.card-carousel-tall :global(figure > div) {
		height: 14rem;
	}
</style>
