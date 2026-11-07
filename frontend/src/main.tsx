import "@fontsource-variable/inter";
import "./index.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { Toaster } from "sonner";

import { Layout } from "@/components/layout";
import { TooltipProvider } from "@/components/ui/tooltip";
import { BlocksPage } from "@/pages/blocks";
import { CampaignDetailPage, CampaignsPage, CampaignWizardPage } from "@/pages/campaigns";
import { AgendaPage } from "@/pages/agenda";
import { CompaniesPage, CompanyPage } from "@/pages/companies";
import { ContactsPage } from "@/pages/contacts";
import { DashboardPage } from "@/pages/dashboard";
import { GuideHome, GuideLayout, GuideSectionPage, StartPage, UseCasePage } from "@/pages/guide-pages";
import { ExclusionsPage } from "@/pages/exclusions";
import { ImportPage } from "@/pages/import";
import { AwaitingPage, FollowupsPage, InboxPage } from "@/pages/inbox";
import { RepliesPage } from "@/pages/replies";
import { SequenceEditorPage } from "@/pages/sequence-editor";
import { SequencesPage } from "@/pages/sequences";
import { SettingsPage } from "@/pages/settings";
import { AuthGate } from "@/pages/login";
import { TeamPage } from "@/pages/team";

// React Query garde les réponses de l'API en mémoire et les rafraîchit quand la fenêtre
// reprend le focus : l'écran reste à jour sans recharger la page.
const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 5_000, retry: 1, refetchOnWindowFocus: true } },
});

// Toutes les pages de la nouvelle interface vivent sous /v2 (le serveur Python renvoie index.html
// pour chacune) ; les anciennes pages restent disponibles à leurs adresses d'origine.
const router = createBrowserRouter(
  [
    {
      path: "/",
      element: <Layout />,
      children: [
        { index: true, element: <DashboardPage /> },
        { path: "sequences", element: <SequencesPage /> },
        { path: "sequences/blocks", element: <BlocksPage /> },
        { path: "sequences/:id", element: <SequenceEditorPage /> },
        { path: "campaigns", element: <CampaignsPage /> },
        { path: "campaigns/new", element: <CampaignWizardPage /> },
        { path: "campaigns/:id", element: <CampaignDetailPage /> },
        { path: "inbox", element: <InboxPage /> },
        { path: "inbox/followups", element: <FollowupsPage /> },
        { path: "inbox/awaiting", element: <AwaitingPage /> },
        { path: "replies", element: <RepliesPage /> },
        { path: "contacts", element: <ContactsPage /> },
        { path: "contacts/import", element: <ImportPage /> },
        { path: "contacts/exclusions", element: <ExclusionsPage /> },
        { path: "companies", element: <CompaniesPage /> },
        { path: "companies/:id", element: <CompanyPage /> },
        { path: "agenda", element: <AgendaPage /> },
        { path: "settings", element: <SettingsPage /> },
        { path: "equipe", element: <TeamPage /> },
        {
          path: "guide", element: <GuideLayout />, children: [
            { index: true, element: <GuideHome /> },
            { path: "bien-demarrer", element: <StartPage /> },
            { path: "cas/:slug", element: <UseCasePage /> },
            { path: ":slug", element: <GuideSectionPage /> },
          ],
        },
        { path: "*", element: <DashboardPage /> },
      ],
    },
  ],
  { basename: "/v2" },
);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={200}>
        <AuthGate>
          <RouterProvider router={router} />
        </AuthGate>
        <Toaster position="bottom-right" richColors closeButton />
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
);
