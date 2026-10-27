<script lang="ts">
  import { api, type Job, type Summary } from '$lib/api';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { CATEGORY_LABELS, formatTimestamp, SOURCE_LABELS, usd } from '$lib/format';
  import { app } from '$lib/state.svelte';
  import { Alert, Button, Card, CardBody, CardHeader, CardTitle, Heading, Text, toastManager } from '@immich/ui';
  import { mdiMagnify, mdiRefresh } from '@mdi/js';

  let summary = $state<Summary | null>(null);
  let error = $state('');

  $effect(() => {
    void app.generation;
    api<Summary>('/summary')
      .then((s) => (summary = s))
      .catch((e) => (error = e.message));
  });

  async function scan(full: boolean) {
    try {
      app.watch(await api<Job>('/scans', { body: { full } }));
    } catch (e) {
      toastManager.danger((e as Error).message);
    }
  }

  const running = $derived(app.job?.status === 'running');
  const problemCats = ['missing', 'wrong_clock', 'timezone', 'scan', 'suspect'];
  const problems = $derived(summary ? problemCats.reduce((n, c) => n + (summary!.categories[c] ?? 0), 0) : 0);
  const sortedIssues = $derived(summary ? Object.entries(summary.issues).sort((a, b) => b[1] - a[1]) : []);
  const maxIssue = $derived(sortedIssues[0]?.[1] ?? 1);
  const lastStats = $derived((summary?.lastScan?.stats ?? {}) as Record<string, unknown>);
</script>

<PageHeader title="Übersicht" description="Analysebericht deiner Bibliothek: Welche Fotos und Videos haben ein fehlendes oder falsches Aufnahmedatum?">
  {#snippet actions()}
    <Button leadingIcon={mdiMagnify} disabled={running} onclick={() => scan(false)}>Bibliothek scannen</Button>
    <Button variant="outline" leadingIcon={mdiRefresh} disabled={running} onclick={() => scan(true)}>Vollständig neu prüfen</Button>
  {/snippet}
</PageHeader>

{#if error}<Alert color="danger">{error}</Alert>{/if}

{#if summary}
  {#if summary.total === 0}
    <Alert color="info" title="Noch kein Scan">Starte den ersten Scan. Dabei wird nichts verändert – nur sehr sichere Fälle werden automatisch korrigiert, wenn das in den Einstellungen aktiviert ist.</Alert>
  {:else}
    <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {#each [
        { label: 'Dateien geprüft', value: summary.total, href: null },
        { label: 'Mit Datumsproblem', value: problems, href: '/unresolved' },
        { label: 'Vorschläge offen', value: summary.suggestions.pending ?? 0, href: '/review' },
        { label: 'Ohne Lösung', value: summary.unresolved, href: '/unresolved?unresolved=1' },
      ] as tile (tile.label)}
        <Card>
          <CardBody>
            <a href={tile.href ?? undefined} class="block">
              <Text color="muted" size="small">{tile.label}</Text>
              <Heading size="giant" class="text-primary">{tile.value.toLocaleString('de-DE')}</Heading>
            </a>
          </CardBody>
        </Card>
      {/each}
    </div>

    <div class="mt-6 grid gap-6 xl:grid-cols-3">
      <Card>
        <CardHeader><CardTitle>Kategorien</CardTitle></CardHeader>
        <CardBody>
          <div class="flex flex-col gap-2">
            {#each Object.entries(summary.categories).sort((a, b) => b[1] - a[1]) as [cat, n] (cat)}
              <a
                href={problemCats.includes(cat) ? `/unresolved?category=${cat}` : undefined}
                class="flex justify-between rounded-lg px-2 py-1 hover:bg-subtle"
              >
                <span>{CATEGORY_LABELS[cat] ?? cat}</span><span class="font-semibold">{n.toLocaleString('de-DE')}</span>
              </a>
            {/each}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader><CardTitle>Gefundene Probleme</CardTitle></CardHeader>
        <CardBody>
          {#if sortedIssues.length === 0}<Text color="muted">Keine Auffälligkeiten.</Text>{/if}
          <div class="flex flex-col gap-2">
            {#each sortedIssues as [issue, n] (issue)}
              <a href="/unresolved?issue={issue}" class="block rounded-lg px-2 py-1 hover:bg-subtle">
                <div class="flex justify-between text-sm"><span>{app.issueLabel(issue)}</span><span class="font-semibold">{n}</span></div>
                <div class="mt-1 h-1.5 rounded-full bg-light-200 dark:bg-light-300">
                  <div class="h-full rounded-full bg-primary" style="width: {(n / maxIssue) * 100}%"></div>
                </div>
              </a>
            {/each}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader><CardTitle>Offene Vorschläge nach Quelle</CardTitle></CardHeader>
        <CardBody>
          {#if Object.keys(summary.pendingBySource).length === 0}<Text color="muted">Nichts zu prüfen.</Text>{/if}
          <div class="flex flex-col gap-2">
            {#each Object.entries(summary.pendingBySource).sort((a, b) => b[1] - a[1]) as [src, n] (src)}
              <a href="/review?source={src}" class="flex justify-between rounded-lg px-2 py-1 hover:bg-subtle">
                <span>{SOURCE_LABELS[src] ?? src}</span><span class="font-semibold">{n}</span>
              </a>
            {/each}
          </div>
          <div class="mt-4 flex flex-wrap gap-x-4 text-sm text-gray-500 dark:text-gray-400">
            <span>Übernommen: {(summary.suggestions.applied ?? 0) + (summary.suggestions.auto_applied ?? 0)}</span>
            <span>davon automatisch: {summary.suggestions.auto_applied ?? 0}</span>
            <span>Claude-Kosten: {usd(summary.claudeSpentUsd)}</span>
          </div>
        </CardBody>
      </Card>
    </div>

    {#if summary.lastScan}
      <Card class="mt-6">
        <CardHeader><CardTitle>Letzter Scan</CardTitle></CardHeader>
        <CardBody>
          <div class="flex flex-wrap gap-x-6 gap-y-1 text-sm">
            <span>Gestartet: {formatTimestamp(summary.lastScan.started_at)}</span>
            <span>Status: {summary.lastScan.status}</span>
            {#if lastStats.assets !== undefined}<span>Dateien: {lastStats.assets}</span>{/if}
            {#if lastStats.changed !== undefined}<span>Neu/geändert: {lastStats.changed}</span>{/if}
            {#if lastStats.suggestions !== undefined}<span>Vorschläge: {lastStats.suggestions}</span>{/if}
            {#if lastStats.auto_applied !== undefined}<span>Automatisch korrigiert: {lastStats.auto_applied}</span>{/if}
          </div>
          {#if lastStats.deep_skipped}<Alert color="warning" class="mt-3">Tiefe Metadatenprüfung übersprungen: {lastStats.deep_skipped}</Alert>{/if}
          {#if lastStats.local_ai_error}<Alert color="warning" class="mt-3">Lokale KI: {lastStats.local_ai_error}</Alert>{/if}
          {#if summary.lastScan.status === 'failed'}<Alert color="danger" class="mt-3">{summary.lastScan.message}</Alert>{/if}
        </CardBody>
      </Card>
    {/if}
  {/if}
{/if}
