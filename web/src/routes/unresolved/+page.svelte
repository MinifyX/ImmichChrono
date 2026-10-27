<script lang="ts">
  import { page } from '$app/state';
  import { api, qs, type AssetView, type Page } from '$lib/api';
  import AssetModal from '$lib/components/AssetModal.svelte';
  import AssetTile from '$lib/components/AssetTile.svelte';
  import ClaudeModal from '$lib/components/ClaudeModal.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { CATEGORY_LABELS } from '$lib/format';
  import { app } from '$lib/state.svelte';
  import { Alert, Button, Field, Input, LoadingSpinner, Select, Switch, Text, toastManager } from '@immich/ui';
  import { mdiCreation, mdiSelectAll, mdiSelectionOff } from '@mdi/js';

  const params = page.url.searchParams;
  let category = $state(params.get('category') ?? '');
  let issue = $state(params.get('issue') ?? '');
  let unresolved = $state(params.get('unresolved') === '1');
  let q = $state('');
  let pageNo = $state(1);
  let data = $state<Page<AssetView> | null>(null);
  let loading = $state(false);
  let selected = $state(new Set<string>());
  let detail = $state<string | null>(null);
  let claudeOpen = $state(false);

  const categoryOptions = [
    { label: 'Alle mit Problem', value: '' },
    ...['missing', 'wrong_clock', 'timezone', 'scan', 'suspect', 'fixed', 'ok'].map((value) => ({
      label: CATEGORY_LABELS[value],
      value,
    })),
  ];
  const issueOptions = $derived([
    { label: 'Alle', value: '' },
    ...Object.entries(app.server?.issueLabels ?? {}).map(([value, label]) => ({ label, value })),
  ]);

  async function load() {
    loading = true;
    try {
      data = await api<Page<AssetView>>(`/assets${qs({ category, issue, unresolved: unresolved || undefined, q, page: pageNo, size: 120 })}`);
    } catch (e) {
      toastManager.danger((e as Error).message);
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    void app.generation;
    void [category, issue, unresolved, q, pageNo];
    load();
  });

  function toggle(id: string) {
    selected = selected.has(id) ? new Set([...selected].filter((x) => x !== id)) : new Set([...selected, id]);
  }
  const pages = $derived(data ? Math.max(1, Math.ceil(data.total / data.size)) : 1);
  const reset = () => (pageNo = 1);
</script>

<PageHeader title="Ungeklärte Dateien" description="Dateien mit Datumsproblem. Wähle Dateien aus, um sie von Claude analysieren zu lassen, oder öffne eine Datei, um das Datum selbst zu setzen.">
  {#snippet actions()}
    {#if selected.size}
      <Button variant="ghost" color="secondary" leadingIcon={mdiSelectionOff} onclick={() => (selected = new Set())}>Auswahl aufheben</Button>
    {/if}
    <Button variant="outline" color="secondary" leadingIcon={mdiSelectAll} disabled={!data?.items.length}
      onclick={() => (selected = new Set([...selected, ...data!.items.map((a) => a.id)]))}>Seite auswählen</Button>
    <Button leadingIcon={mdiCreation} disabled={!selected.size || selected.size > 500} onclick={() => (claudeOpen = true)}>
      Mit Claude analysieren ({selected.size})
    </Button>
  {/snippet}
</PageHeader>

<div class="mb-6 grid items-end gap-4 sm:grid-cols-2 lg:grid-cols-4">
  <Field label="Kategorie"><Select options={categoryOptions} bind:value={category} onChange={reset} /></Field>
  <Field label="Problem"><Select options={issueOptions} bind:value={issue} onChange={reset} /></Field>
  <Field label="Suche (Dateiname/Pfad)"><Input bind:value={q} oninput={reset} /></Field>
  <Field label="Nur ohne offenen Vorschlag">
    <Switch bind:checked={unresolved} onCheckedChange={reset} />
  </Field>
</div>

{#if loading && !data}
  <div class="flex justify-center p-10"><LoadingSpinner size="large" /></div>
{:else if data && data.items.length === 0}
  <Alert color="success" title="Nichts gefunden">Für diesen Filter gibt es keine Dateien.</Alert>
{:else if data}
  <Text size="small" color="muted" class="mb-3">{data.total.toLocaleString('de-DE')} Dateien</Text>
  <div class="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 2xl:grid-cols-8">
    {#each data.items as a (a.id)}
      <AssetTile asset={a} selected={selected.has(a.id)} onToggle={() => toggle(a.id)} onOpen={() => (detail = a.id)} />
    {/each}
  </div>
  {#if pages > 1}
    <div class="mt-6 flex items-center justify-center gap-3">
      <Button size="small" variant="ghost" disabled={pageNo <= 1} onclick={() => pageNo--}>Zurück</Button>
      <Text size="small">Seite {pageNo} von {pages}</Text>
      <Button size="small" variant="ghost" disabled={pageNo >= pages} onclick={() => pageNo++}>Weiter</Button>
    </div>
  {/if}
{/if}

{#if detail}
  <AssetModal id={detail} onClose={() => (detail = null)} onChange={load} />
{/if}
{#if claudeOpen}
  <ClaudeModal assetIds={[...selected]} onClose={() => ((claudeOpen = false), (selected = new Set()))} />
{/if}
