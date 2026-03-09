<script lang="ts">
	import { createEventDispatcher } from 'svelte';

	export let value: string | null = ''; // ISO yyyy-mm-dd
	export let id: string = '';
	export let name: string = '';
	export let inputClass: string = 'input input-bordered w-full';
	export let disabled: boolean = false;
	export let min: string | null | undefined = undefined;
	export let max: string | null | undefined = undefined;
	export let required: boolean = false;
	export let readonly: boolean = false;

	const dispatch = createEventDispatcher<{ change: Event }>();

	let nativeInput: HTMLInputElement;

	$: normalizedValue = value ?? '';
	$: normalizedMin = min ?? undefined;
	$: normalizedMax = max ?? undefined;

	$: displayDate = formatDate(normalizedValue);

	function formatDate(iso: string): string {
		if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return '';
		const [y, m, d] = iso.split('-');
		return `${d}/${m}/${y}`;
	}

	function openPicker() {
		if (!disabled && !readonly) nativeInput?.showPicker?.();
	}

	function handleChange(e: Event) {
		value = (e.currentTarget as HTMLInputElement).value;
		dispatch('change', e);
	}
</script>

<div class="relative w-full">
	<button
		type="button"
		class="{inputClass} text-left flex items-center justify-between"
		on:click={openPicker}
		disabled={disabled || readonly}
	>
		<span class={displayDate ? '' : 'opacity-40'}>{displayDate || 'DD/MM/YYYY'}</span>
		<svg
			xmlns="http://www.w3.org/2000/svg"
			class="h-4 w-4 opacity-60"
			viewBox="0 0 24 24"
			fill="currentColor"
		>
			<path
				d="M19 3h-1V1h-2v2H8V1H6v2H5c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 18H5V8h14v13zM7 10h5v5H7z"
			/>
		</svg>
	</button>
	<input
		bind:this={nativeInput}
		type="date"
		{id}
		{name}
		value={normalizedValue}
		min={normalizedMin}
		max={normalizedMax}
		{required}
		{readonly}
		on:change={handleChange}
		{disabled}
		tabindex="-1"
		aria-hidden="true"
		style="position:absolute;opacity:0;width:1px;height:1px;top:0;left:0;pointer-events:none;z-index:-1"
	/>
</div>
