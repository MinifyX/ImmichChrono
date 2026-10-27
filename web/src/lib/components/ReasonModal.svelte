<script lang="ts">
  import type { DecisionAction, Reason } from '$lib/api';
  import { app } from '$lib/state.svelte';
  import { Button, Modal, ModalBody, ModalFooter, Text } from '@immich/ui';

  type Props = {
    action: DecisionAction;
    title: string;
    prompt?: string;
    confirmText: string;
    danger?: boolean;
    /** null = abbrechen (nichts passiert), sonst Entscheidung mit optionalem Grund. */
    onClose: (result: Reason | null) => void;
  };
  const { action, title, prompt, confirmText, danger = false, onClose }: Props = $props();

  const options = $derived((app.server?.decisionReasons ?? []).filter((r) => r.actions.includes(action)));
  let reason = $state<string | null>(null);
  let note = $state('');

  const done = (withReason: boolean) =>
    onClose(withReason ? { reason, note: note.trim() || null } : { reason: null, note: null });
</script>

<Modal {title} onClose={() => onClose(null)} size="small">
  <ModalBody>
    <div class="flex flex-col gap-3">
      {#if prompt}<Text size="small">{prompt}</Text>{/if}
      <Text size="small" color="muted">Warum? Hilft später, Muster in deinen Entscheidungen zu finden.</Text>
      <div class="flex flex-wrap gap-2" role="radiogroup" aria-label="Grund">
        {#each options as r (r.code)}
          <button
            type="button"
            role="radio"
            aria-checked={reason === r.code}
            class="rounded-full border px-3 py-1 text-sm transition-colors {reason === r.code
              ? 'border-primary bg-primary text-light'
              : 'border-light-300 hover:bg-subtle'}"
            onclick={() => (reason = reason === r.code ? null : r.code)}
          >
            {r.label}
          </button>
        {/each}
      </div>
      <textarea
        bind:value={note}
        maxlength="500"
        rows="2"
        placeholder="Eigener Grund / Notiz (optional)"
        class="w-full rounded-xl border border-light-300 bg-transparent px-3 py-2 text-sm focus:border-primary focus:outline-none"
      ></textarea>
    </div>
  </ModalBody>
  <ModalFooter>
    <div class="flex w-full justify-end gap-2">
      <Button variant="ghost" color="secondary" onclick={() => onClose(null)}>Abbrechen</Button>
      <Button variant="outline" color="secondary" onclick={() => done(false)}>Ohne Grund</Button>
      <Button color={danger ? 'danger' : 'primary'} disabled={!reason && !note.trim()} onclick={() => done(true)}>
        {confirmText}
      </Button>
    </div>
  </ModalFooter>
</Modal>
