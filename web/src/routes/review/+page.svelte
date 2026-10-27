<script lang="ts">
  import { page } from '$app/state';
  import { api, qs, type Page, type Reason, type Suggestion } from '$lib/api';
  import AssetModal from '$lib/components/AssetModal.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import ReasonModal from '$lib/components/ReasonModal.svelte';
  import SuggestionCard from '$lib/components/SuggestionCard.svelte';
  import { CATEGORY_LABELS, SOURCE_LABELS } from '$lib/format';
  import { app } from '$lib/state.svelte';
  import { Alert, Button, Field, Input, LoadingSpinner, Select, Text, toastManager } from '@immich/ui';
  import { mdiCheck, mdiCheckAll, mdiClose, mdiSelectAll } from '@mdi/js';

  const all = { label: 'Alle', value: '' };
  const sourceOptions = [all, ...Object.entries(SOURCE_LABELS).map(([value, label]) => ({ label, value }))];
  const categoryOptions = [
    all,
    ...['missing', 'wrong_clock', 'timezone', 'scan', 'suspect'].map((value) => ({ label: CATEGORY_LABELS[value], value })),
  ];
  const confOptions = [
    { label: 'Alle', value: '0' },
    { label: 'ab 90 %', value: '0.9' },
    { label: 'ab 75 %', value: '0.75' },
    { label: 'ab 50 %', value: '0.5' },
  ];

  let source = $state(page.url.searchParams.get('source') ?? '');
  let category = $state('');
  let minConf = $state('0');
  let q = $state('');
  let pageNo = $state(1);
  let data = $state<Page<Suggestion> | null>(null);
  let loading = $state(false);
  let selected = $state(new Set<number>());
  let detail = $state<string | null>(null);
  let ask = $state<'apply' | 'reject' | 'all' | null>(null);
  let busy = $state(false);

  const filter = $derived({ source, category, min_conf: Number(minConf) || undefined, q });

  async function load() {
    loading = true;
    try {
      data = await api<Page<Suggestion>>(`/suggestions${qs({ ...filter, page: pageNo })}`);
      selected = new Set([...selected].filter((id) => data!.items.some((s) => s.id === id)));
    } catch (e) {
      toastManager.danger((e as Error).message);
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    void app.generation;
    void filter;
    void pageNo;
    load();
  });

  function toggle(id: number) {
    selected = selected.has(id) ? new Set([...selected].filter((x) => x !== id)) : new Set([...selected, id]);
  }

  async function run(path: string, body: unknown, ok: (r: { applied?: number; rejected?: number; failed?: unknown[] }) => string) {
    busy = true;
    try {
      const r = await api<{ applied?: number; rejected?: number; failed?: unknown[] }>(path, { body });
      toastManager.success(ok(r));
      if (r.failed?.length) toastManager.warning(`${r.failed.length} konnten nicht geändert werden`);
      selected = new Set();
      await load();
    } catch (e) {
      toastManager.danger((e as Error).message);
    } finally {
      busy = false;
    }
  }

  function decide(kind: 'apply' | 'reject' | 'all', why: Reason | null) {
    ask = null;
    if (!why) return;
    if (kind === 'apply') run('/suggestions/apply', { ids: [...selected], ...why }, (r) => `${r.applied} Dateien neu datiert`);
    else if (kind === 'reject') run('/suggestions/reject', { ids: [...selected], ...why }, (r) => `${r.rejected} Vorschläge abgelehnt`);
    else run('/suggestions/apply-filter', { ...filter, ...why }, (r) => `${r.applied} Dateien neu datiert`);
  }
  const pages = $derived(data ? Math.max(1, Math.ceil(data.total / data.size)) : 1);
</script>

<PageHeader title="Vorschläge prüfen" description="Kontrolliere die erkannten Aufnahmedaten. Übernommene Änderungen werden in Immich gespeichert und lassen sich im Verlauf zurücknehmen.">
  {#snippet actions()}
    <Button variant="outline" color="secondary" leadingIcon={mdiSelectAll} disabled={!data?.items.length}
      onclick={() => (selected = new Set(data!.items.map((s) => s.id)))}>Seite auswählen</Button>
    <Button variant="outline" color="danger" leadingIcon={mdiClose} disabled={!selected.size || busy} onclick={() => (ask = 'reject')}>
      Ablehnen ({selected.size})
    </Button>
    <Button leadingIcon={mdiCheck} disabled={!selected.size || busy} onclick={() => (ask = 'apply')}>Übernehmen ({selected.size})</Button>
    <Button variant="outline" leadingIcon={mdiCheckAll} disabled={!data?.total || busy} onclick={() => (ask = 'all')}>
      Alle gefilterten ({data?.total ?? 0})
    </Button>
  {/snippet}
</PageHeader>

<div class="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
  <Field label="Quelle"><Select options={sourceOptions} bind:value={source} onChange={() => (pageNo = 1)} /></Field>
  <Field label="Kategorie"><Select options={categoryOptions} bind:value={category} onChange={() => (pageNo = 1)} /></Field>
  <Field label="Sicherheit"><Select options={confOptions} bind:value={minConf} onChange={() => (pageNo = 1)} /></Field>
  <Field label="Suche (Dateiname/Pfad)"><Input bind:value={q} oninput={() => (pageNo = 1)} /></Field>
</div>

{#if loading && !data}
  <div class="flex justify-center p-10"><LoadingSpinner size="large" /></div>
{:else if data && data.items.length === 0}
  <Alert color="success" title="Alles geprüft">Für diesen Filter gibt es keine offenen Vorschläge.</Alert>
{:else if data}
  <div class="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
    {#each data.items as s (s.id)}
      <SuggestionCard suggestion={s} selected={selected.has(s.id)} onToggle={() => toggle(s.id)} onOpen={() => (detail = s.asset.id)} />
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

{#if ask === 'all'}
  <ReasonModal
    action="applied"
    title="Alle gefilterten Vorschläge übernehmen?"
    prompt="{data?.total ?? 0} Dateien erhalten ein neues Aufnahmedatum in Immich. Jede Änderung kann im Verlauf zurückgenommen werden. Der Grund gilt für alle."
    confirmText="Übernehmen"
    onClose={(why) => decide('all', why)}
  />
{:else if ask}
  <ReasonModal
    action={ask === 'apply' ? 'applied' : 'rejected'}
    title={ask === 'apply' ? `${selected.size} Vorschläge übernehmen` : `${selected.size} Vorschläge ablehnen`}
    prompt={selected.size > 1 ? 'Der Grund gilt für alle ausgewählten.' : undefined}
    confirmText={ask === 'apply' ? 'Übernehmen' : 'Ablehnen'}
    danger={ask === 'reject'}
    onClose={(why) => decide(ask!, why)}
  />
{/if}
