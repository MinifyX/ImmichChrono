<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import { api, type User } from '$lib/api';
  import JobBanner from '$lib/components/JobBanner.svelte';
  import { app } from '$lib/state.svelte';
  import {
    AppShell,
    AppShellHeader,
    AppShellSidebar,
    Button,
    IconButton,
    LoadingSpinner,
    Logo,
    NavbarItem,
    Text,
    ThemeSwitcher,
    TooltipProvider,
  } from '@immich/ui';
  import {
    mdiCamera,
    mdiChartBox,
    mdiChartBoxOutline,
    mdiCameraOutline,
    mdiCheckDecagram,
    mdiCheckDecagramOutline,
    mdiCog,
    mdiCogOutline,
    mdiHelpCircle,
    mdiHelpCircleOutline,
    mdiHistory,
    mdiLogout,
    mdiMenu,
    mdiViewDashboard,
    mdiViewDashboardOutline,
  } from '@mdi/js';
  import type { Snippet } from 'svelte';
  import '../app.css';

  const { children }: { children: Snippet } = $props();
  let ready = $state(false);
  let sidebarOpen = $state(window.innerWidth >= 768);
  const isLogin = $derived(page.url.pathname.startsWith('/login'));

  $effect(() => {
    if (ready) return;
    (async () => {
      try {
        await app.loadServer();
        app.user = await api<User>('/auth/me');
        await app.refreshJob();
      } catch {
        app.user = null;
        if (!isLogin) await goto('/login');
      }
      ready = true;
    })();
  });

  async function logout() {
    await api('/auth/logout', { method: 'POST' }).catch(() => {});
    app.user = null;
    app.stop();
    await goto('/login');
  }

  const nav = [
    { href: '/', title: 'Übersicht', icon: mdiViewDashboardOutline, activeIcon: mdiViewDashboard },
    { href: '/review', title: 'Prüfen', icon: mdiCheckDecagramOutline, activeIcon: mdiCheckDecagram },
    { href: '/unresolved', title: 'Ungeklärt', icon: mdiHelpCircleOutline, activeIcon: mdiHelpCircle },
    { href: '/camera', title: 'Kamera-Uhr', icon: mdiCameraOutline, activeIcon: mdiCamera },
    { href: '/history', title: 'Verlauf', icon: mdiHistory, activeIcon: mdiHistory },
    { href: '/insights', title: 'Auswertung', icon: mdiChartBoxOutline, activeIcon: mdiChartBox },
    { href: '/settings', title: 'Einstellungen', icon: mdiCogOutline, activeIcon: mdiCog },
  ];
  const isActive = (href: string) =>
    href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href);
</script>

<svelte:head><title>ImmichChrono</title></svelte:head>

<TooltipProvider>
{#if !ready}
  <div class="flex h-dvh items-center justify-center"><LoadingSpinner size="giant" /></div>
{:else if isLogin || !app.user}
  {@render children()}
{:else}
  <AppShell>
    <AppShellHeader>
      <div class="flex h-full w-full items-center gap-2 px-3 sm:px-6">
        <IconButton icon={mdiMenu} variant="ghost" shape="round" color="secondary" aria-label="Menü" onclick={() => (sidebarOpen = !sidebarOpen)} />
        <a href="/" class="flex items-center gap-2">
          <Logo variant="icon" size="medium" />
          <span class="text-xl font-semibold tracking-tight text-primary sm:text-2xl">ImmichChrono</span>
        </a>
        <span class="grow"></span>
        <ThemeSwitcher />
        <div class="hidden text-end sm:block">
          <Text size="small" fontWeight="semi-bold">{app.user.name}</Text>
          <Text size="tiny" color="muted">{app.user.email}</Text>
        </div>
        <Button size="small" variant="ghost" color="secondary" leadingIcon={mdiLogout} onclick={logout}>Abmelden</Button>
      </div>
    </AppShellHeader>
    <AppShellSidebar bind:open={sidebarOpen}>
      <div class="flex h-full flex-col justify-between pe-4 pt-4">
        <div class="flex flex-col gap-1">
          {#each nav as item (item.href)}
            <div role="none" onclick={() => window.innerWidth < 768 && (sidebarOpen = false)}>
              <NavbarItem {...item} active={isActive(item.href)} />
            </div>
          {/each}
        </div>
        <Text size="tiny" color="muted" class="p-4">
          ImmichChrono {app.server?.version} · Immich {app.server?.immichVersion ?? '?'}
        </Text>
      </div>
    </AppShellSidebar>
    <div class="mx-auto w-full max-w-screen-2xl p-4 sm:p-8">
      <JobBanner />
      {@render children()}
    </div>
  </AppShell>
{/if}
</TooltipProvider>
