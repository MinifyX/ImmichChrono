<script lang="ts">
  import { api, type AssetView } from '$lib/api';
  import AssetThumb from '$lib/components/AssetThumb.svelte';
  import PageHeader from '$lib/components/PageHeader.svelte';
  import { formatDate, formatShift } from '$lib/format';
  import { app } from '$lib/state.svelte';
  import {
    Alert,
    Button,
    Card,
    CardBody,
    CardHeader,
    CardTitle,
    ConfirmModal,
    Field,
    Input,
    Select,
    Table,
    TableBody,
    TableCell,
    TableHeader,
    TableHeading,
    TableRow,
    Text,
    toastManager,
  } from '@immich/ui';
  import { mdiCheck, mdiEye } from '@mdi/js';

  type Camera = { make: string | null; model: string | null; count: number; first: string; last: string };
  type Preview = { offsetSeconds: number; count: number; items: { asset: AssetView; from: string; to: string }[] };

  let cameras = $state<Camera[]>([]);
  let camKey = $state('');
  let start = $state('');
  let end = $state('');
  let mode = $state<'offset' | 'reference'>('reference');
  let days = $state('0');
  let hours = $state('0');
  let minutes = $state('0');
  let refAsset = $state('');
  let refDate = $state('');
  let preview = $state<Preview | null>(null);
  let error = $state('');
  let confirm = $state(false);
  let busy = $state(false);

  $effect(() => {
    void app.generation;
    api<Camera[]>('/cameras').then((c) => (cameras = c));
  });

  const key = (c: Camera) => JSON.stringify([c.make, c.model]);
  const camera = $derived(cameras.find((c) => key(c) === camKey));
  const withSeconds = (v: string) => (v && v.length === 16 ? `${v}:00` : v || null);

  const body = $derived({
    make: camera?.make ?? null,
    model: camera?.model ?? null,
    start: withSeconds(start),
    end: withSeconds(end),
    ...(mode === 'offset'
      ? { offset_seconds: ((Number(days) || 0) * 24 * 60 + (Number(hours) || 0) * 60 + (Number(minutes) || 0)) * 60 }
      : { reference_asset_id: refAsset.trim() || null, reference_true_date: withSeconds(refDate) }),
  });

  async function loadPreview() {
    error = '';
    try {
      preview = await api<Preview>('/camera-shift/preview', { body });
    } catch (e) {
      preview = null;
      error = (e as Error).message;
    }
  }

  async function apply() {
    busy = true;
    try {
      const r = await api<{ applied: number; failed: unknown[] }>('/camera-shift/apply', { body });
      toastManager.success(`${r.applied} Dateien verschoben`);
      if (r.failed.length) toastManager.warning(`${r.failed.length} fehlgeschlagen`);
      preview = null;
      app.generation++;
    } catch (e) {
      toastManager.danger((e as Error).message);
    } finally {
      busy = false;
    }
  }

  const offsetText = (s: number) => formatShift('2000-01-01T00:00:00', new Date(Date.UTC(2000, 0, 1) + s * 1000).toISOString());
</script>

<PageHeader title="Kamera-Uhr korrigieren" description="Wenn die Uhr einer Kamera falsch eingestellt war, verschiebe alle ihre Aufnahmen in einem Zeitraum um denselben Versatz. Am einfachsten: ein Bild mit bekanntem echten Zeitpunkt als Referenz wählen." />

<div class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
  <Card>
    <CardHeader><CardTitle>Kamera und Zeitraum</CardTitle></CardHeader>
    <CardBody>
      <div class="flex flex-col gap-4">
        <Field label="Kamera">
          <Select
            placeholder="Kamera wählen"
            options={cameras.map((c) => ({
              value: key(c),
              label: `${[c.make, c.model].filter(Boolean).join(' ')} (${c.count})`,
            }))}
            bind:value={camKey}
          />
        </Field>
        {#if camera}
          <Text size="small" color="muted">Aufnahmen von {formatDate(camera.first)} bis {formatDate(camera.last)}</Text>
        {/if}
        <div class="grid gap-4 sm:grid-cols-2">
          <Field label="Von (aktuelles Datum, optional)"><Input type="datetime-local" bind:value={start} /></Field>
          <Field label="Bis (optional)"><Input type="datetime-local" bind:value={end} /></Field>
        </div>
        <Field label="Versatz bestimmen">
          <Select
            options={[
              { value: 'reference', label: 'Über ein Referenzbild' },
              { value: 'offset', label: 'Versatz direkt eingeben' },
            ]}
            bind:value={mode}
          />
        </Field>
        {#if mode === 'offset'}
          <div class="grid grid-cols-3 gap-4">
            <Field label="Tage"><Input type="number" bind:value={days} /></Field>
            <Field label="Stunden"><Input type="number" bind:value={hours} /></Field>
            <Field label="Minuten"><Input type="number" bind:value={minutes} /></Field>
          </div>
          <Text size="tiny" color="muted">Negative Werte verschieben in die Vergangenheit.</Text>
        {:else}
          <Field label="Referenzbild (Immich-ID)" description="Die ID steht in der Immich-URL: …/photos/<ID>">
            <Input bind:value={refAsset} />
          </Field>
          <Field label="Echter Aufnahmezeitpunkt des Referenzbilds"><Input type="datetime-local" step="1" bind:value={refDate} /></Field>
        {/if}
        {#if error}<Alert color="danger">{error}</Alert>{/if}
        <div class="flex gap-2">
          <Button variant="outline" leadingIcon={mdiEye} disabled={!camera} onclick={loadPreview}>Vorschau</Button>
          <Button leadingIcon={mdiCheck} disabled={!preview?.count || busy} onclick={() => (confirm = true)}>
            Anwenden ({preview?.count ?? 0})
          </Button>
        </div>
      </div>
    </CardBody>
  </Card>

  <Card>
    <CardHeader>
      <CardTitle>Vorschau {preview ? `– Versatz ${offsetText(preview.offsetSeconds)}` : ''}</CardTitle>
    </CardHeader>
    <CardBody>
      {#if !preview}
        <Text color="muted">Wähle eine Kamera und klicke auf „Vorschau“.</Text>
      {:else}
        <Text size="small" class="mb-3">{preview.count} Dateien betroffen{preview.count > 200 ? ' (die ersten 200 werden gezeigt)' : ''}.</Text>
        <div class="max-h-[60vh] overflow-auto">
          <Table size="small" striped>
            <TableHeader>
              <TableHeading class="w-16"></TableHeading>
              <TableHeading>Datei</TableHeading>
              <TableHeading>Bisher</TableHeading>
              <TableHeading>Neu</TableHeading>
            </TableHeader>
            <TableBody>
              {#each preview.items as it (it.asset.id)}
                <TableRow>
                  <TableCell><AssetThumb id={it.asset.id} class="size-12 rounded" /></TableCell>
                  <TableCell class="truncate">{it.asset.fileName}</TableCell>
                  <TableCell>{formatDate(it.from)}</TableCell>
                  <TableCell class="font-semibold text-primary">{formatDate(it.to)}</TableCell>
                </TableRow>
              {/each}
            </TableBody>
          </Table>
        </div>
      {/if}
    </CardBody>
  </Card>
</div>

{#if confirm}
  <ConfirmModal
    title="Kamera-Uhr korrigieren?"
    prompt="{preview?.count} Dateien werden in Immich um {offsetText(preview?.offsetSeconds ?? 0)} verschoben. Das lässt sich im Verlauf pro Datei zurücknehmen."
    confirmText="Anwenden"
    onClose={(ok: boolean) => {
      confirm = false;
      if (ok) apply();
    }}
  />
{/if}
