<script lang="ts">
  import { api, type DecisionRow, type DecisionStats } from '$lib/api';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { percent, SOURCE_LABELS } from '$lib/format';
  import { app } from '$lib/state.svelte';
  import {
    Alert,
    Button,
    Card,
    CardBody,
    CardHeader,
    CardTitle,
    LoadingSpinner,
    Table,
    TableBody,
    TableCell,
    TableHeader,
    TableHeading,
    TableRow,
    toastManager,
  } from '@immich/ui';
  import { mdiDownload } from '@mdi/js';

  let stats = $state<DecisionStats | null>(null);

  $effect(() => {
    void app.generation;
    api<DecisionStats>('/decisions/stats')
      .then((s) => (stats = s))
      .catch((e: Error) => toastManager.danger(e.message));
  });

  const ACTION_LABELS: Record<string, string> = {
    applied: 'Übernommen',
    auto_applied: 'Automatisch',
    rejected: 'Abgelehnt',
    reverted: 'Zurückgenommen',
    manual: 'Manuell',
    camera_shift: 'Kamera-Uhr',
  };

  const sections = $derived(
    stats
      ? [
          { title: 'Nach Quelle', rows: stats.bySource, label: (k: string) => SOURCE_LABELS[k] ?? k },
          { title: 'Nach Kamera', rows: stats.byCamera, label: (k: string) => k },
          { title: 'Nach Problemart', rows: stats.byIssue, label: (k: string) => (k === 'keins' ? 'keins' : app.issueLabel(k)) },
          { title: 'Nach Dateinamen-Muster', rows: stats.byPattern, label: (k: string) => k },
        ]
      : [],
  );
  const rate = (r: DecisionRow) => (r.rate === null ? '–' : percent(r.rate));
</script>

<PageHeader
  title="Auswertung"
  description="Wie oft du Vorschläge übernimmst oder ablehnst – je Quelle, Kamera und Problemart. Gezählt wird die letzte Entscheidung pro Vorschlag; Quote = übernommen ÷ (übernommen + abgelehnt/zurückgenommen)."
>
  {#snippet actions()}
    <Button variant="outline" leadingIcon={mdiDownload} href="/api/decisions/export" download data-sveltekit-reload>Protokoll exportieren (JSONL)</Button>
  {/snippet}
</PageHeader>

{#if !stats}
  <div class="flex justify-center p-10"><LoadingSpinner size="large" /></div>
{:else if stats.total === 0}
  <Alert color="info">Noch keine Entscheidungen protokolliert.</Alert>
{:else}
  <div class="grid gap-6 xl:grid-cols-2">
    <Card>
      <CardHeader><CardTitle>Gründe</CardTitle></CardHeader>
      <CardBody>
        <Table size="small" striped>
          <TableHeader>
            <TableHeading>Entscheidung</TableHeading>
            <TableHeading>Grund</TableHeading>
            <TableHeading class="text-right">Anzahl</TableHeading>
          </TableHeader>
          <TableBody>
            {#each stats.reasons as r (`${r.action}:${r.reason}`)}
              <TableRow>
                <TableCell>{ACTION_LABELS[r.action] ?? r.action}</TableCell>
                <TableCell>{r.label}</TableCell>
                <TableCell class="text-right">{r.count}</TableCell>
              </TableRow>
            {/each}
          </TableBody>
        </Table>
      </CardBody>
    </Card>
    {#each sections as sec (sec.title)}
      <Card>
        <CardHeader><CardTitle>{sec.title}</CardTitle></CardHeader>
        <CardBody>
          <div class="max-h-[50vh] overflow-auto">
            <Table size="small" striped>
              <TableHeader>
                <TableHeading></TableHeading>
                <TableHeading class="text-right">Quote</TableHeading>
                <TableHeading class="text-right">Übern.</TableHeading>
                <TableHeading class="text-right">Abgel.</TableHeading>
                <TableHeading class="text-right">Auto</TableHeading>
                <TableHeading class="text-right">Manuell</TableHeading>
              </TableHeader>
              <TableBody>
                {#each sec.rows as r (r.key)}
                  <TableRow>
                    <TableCell class="truncate" title={r.key}>{sec.label(r.key)}</TableCell>
                    <TableCell class="text-right font-semibold">{rate(r)}</TableCell>
                    <TableCell class="text-right">{r.accepted}</TableCell>
                    <TableCell class="text-right">{r.rejected}</TableCell>
                    <TableCell class="text-right">{r.auto}</TableCell>
                    <TableCell class="text-right">{r.manual}</TableCell>
                  </TableRow>
                {/each}
              </TableBody>
            </Table>
          </div>
        </CardBody>
      </Card>
    {/each}
  </div>
{/if}
