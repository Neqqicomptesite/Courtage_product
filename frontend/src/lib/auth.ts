// Connexion des employés (Supabase Auth). Sur le poste unique (V2), rien ne change :
// /api/auth/config répond server_mode=false et l'appli s'ouvre directement.
import { createClient, type Session, type SupabaseClient } from "@supabase/supabase-js";

export type AuthConfig = { server_mode: boolean; supabase_url: string; publishable_key: string; product_name?: string };

let client: SupabaseClient | null = null;
/** Vrai quand l'appli tourne sur le serveur en ligne (V3) : le guide adapte ses explications. */
export let SERVER_MODE = false;
/** Nom du produit, fourni par le serveur (variable PRODUCT_NAME). */
export let PRODUCT_NAME = "Cotalis";
let currentToken: string | null = null;

export function supabase(): SupabaseClient | null {
  return client;
}

/** Recopie le jeton dans un cookie lu par le serveur pour les liens ouverts directement
 *  (export Excel, pièces jointes, images des mails). Accepté seulement en lecture (GET). */
function syncCookie(session: Session | null) {
  currentToken = session?.access_token ?? null;
  const secure = location.protocol === "https:" ? "; Secure" : "";
  document.cookie = currentToken
    ? `oddo_at=${currentToken}; Path=/api; SameSite=Strict; Max-Age=${60 * 60 * 24}${secure}`
    : `oddo_at=; Path=/api; SameSite=Strict; Max-Age=0${secure}`;
}

export async function loadAuthConfig(): Promise<AuthConfig> {
  const res = await fetch("/api/auth/config", { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`Serveur injoignable (${res.status}).`);
  const cfg = (await res.json()) as AuthConfig;
  SERVER_MODE = cfg.server_mode;
  if (cfg.product_name) { PRODUCT_NAME = cfg.product_name; document.title = cfg.product_name; }
  if (cfg.server_mode && !client) {
    client = createClient(cfg.supabase_url, cfg.publishable_key, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true, flowType: "implicit" },
    });
    client.auth.onAuthStateChange((_event, session) => syncCookie(session));
  }
  return cfg;
}

/** Jeton à joindre aux appels de l'API (rafraîchi automatiquement par Supabase). */
export async function accessToken(): Promise<string | null> {
  if (!client) return null;
  const { data } = await client.auth.getSession();
  if (data.session?.access_token !== currentToken) syncCookie(data.session);
  return data.session?.access_token ?? null;
}

export async function signOut() {
  if (client) await client.auth.signOut();
  syncCookie(null);
  location.assign("/v2/");
}

/** Prévenu par api.ts quand le serveur répond « connexion requise » (session expirée…). */
export const AUTH_LOST = "oddo-auth-lost";
