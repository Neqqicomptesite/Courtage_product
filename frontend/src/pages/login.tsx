// V3 : écran de connexion, choix du mot de passe (invitation / mot de passe oublié) et
// « garde » qui n'affiche l'appli qu'à un employé connecté. Sans effet sur le poste unique.
import { Loader2, LogOut } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useState, type FormEvent, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError, type Me } from "@/lib/api";
import { AUTH_LOST, loadAuthConfig, signOut, supabase } from "@/lib/auth";

const MeContext = createContext<Me | null>(null);

/** L'employé connecté (ou { server_mode: false } sur le poste unique). */
export function useMe(): Me | null {
  return useContext(MeContext);
}

type State =
  | { k: "loading" }
  | { k: "login"; notice?: string }
  | { k: "set-password"; reason: "invite" | "recovery" }
  | { k: "refused"; message: string }
  | { k: "error"; message: string }
  | { k: "ready"; me: Me };

// Lu AVANT que Supabase ne consomme le lien (#access_token=…&type=invite).
function linkKind(): { type: string | null; error: string | null } {
  const h = new URLSearchParams(location.hash.replace(/^#/, ""));
  return { type: h.get("type"), error: h.get("error_description") };
}

export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ k: "loading" });

  const resolve = useCallback(async (afterPassword = false) => {
    try {
      const me = await api.me();
      setState({ k: "ready", me });
      if (afterPassword) history.replaceState(null, "", location.pathname + location.search);
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) setState({ k: "refused", message: e.message });
      else if (e instanceof ApiError && e.status === 401) setState({ k: "login" });
      else setState({ k: "error", message: e instanceof Error ? e.message : String(e) });
    }
  }, []);

  useEffect(() => {
    const link = linkKind();
    let cancelled = false;
    (async () => {
      try {
        const cfg = await loadAuthConfig();
        if (cancelled) return;
        if (!cfg.server_mode) return void resolve();
        const sb = supabase()!;
        sb.auth.onAuthStateChange((event) => {
          if (event === "PASSWORD_RECOVERY") setState({ k: "set-password", reason: "recovery" });
          if (event === "SIGNED_OUT") setState({ k: "login" });
        });
        const { data } = await sb.auth.getSession();
        if (cancelled) return;
        if (link.error) return setState({ k: "login", notice: "Ce lien n'est plus valable (il a peut-être déjà servi ou expiré). Connectez-vous, ou demandez un nouveau lien." });
        if (!data.session) return setState({ k: "login" });
        if (link.type === "invite" || link.type === "recovery") return setState({ k: "set-password", reason: link.type });
        await resolve();
      } catch (e) {
        setState({ k: "error", message: e instanceof Error ? e.message : String(e) });
      }
    })();
    const lost = () => void supabase()?.auth.getSession().then(({ data }) =>
      setState(data.session ? { k: "error", message: "Le serveur a refusé la connexion. Rechargez la page." }
        : { k: "login", notice: "Votre session a expiré : reconnectez-vous." }));
    window.addEventListener(AUTH_LOST, lost);
    return () => { cancelled = true; window.removeEventListener(AUTH_LOST, lost); };
  }, [resolve]);

  if (state.k === "ready") return <MeContext.Provider value={state.me}>{children}</MeContext.Provider>;
  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 px-4 py-10">
      <div className="w-full max-w-sm rounded-xl border bg-card p-7 shadow-sm">
        <img src="/static/v2/logo-oddo.png" alt="ODDO Assurances" className="h-10 w-auto dark:hidden" />
        <img src="/static/v2/logo-oddo-dark.png" alt="ODDO Assurances" className="hidden h-10 w-auto dark:block" />
        <p className="mb-6 mt-2 text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">Séquences</p>
        {state.k === "loading" && <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Chargement…</p>}
        {state.k === "login" && <LoginForm notice={state.notice} onDone={() => void resolve()} />}
        {state.k === "set-password" && <SetPasswordForm reason={state.reason} onDone={() => void resolve(true)} />}
        {(state.k === "refused" || state.k === "error") && (
          <div className="space-y-4">
            <p className="text-sm" role="alert">{state.message}</p>
            <Button variant="outline" className="w-full" onClick={() => void signOut()}><LogOut /> Se déconnecter</Button>
          </div>
        )}
      </div>
    </div>
  );
}

function LoginForm({ notice, onDone }: { notice?: string; onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(notice ?? null);
  const [forgot, setForgot] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null); setInfo(null);
    const sb = supabase()!;
    if (forgot) {
      const { error } = await sb.auth.resetPasswordForEmail(email.trim(), { redirectTo: `${location.origin}/v2/` });
      setBusy(false);
      if (error) return setError("Envoi impossible pour le moment. Réessayez dans quelques minutes.");
      setForgot(false);
      return setInfo("Si cette adresse a un compte, un email vient de partir avec un lien pour choisir un nouveau mot de passe.");
    }
    const { error } = await sb.auth.signInWithPassword({ email: email.trim(), password });
    setBusy(false);
    if (error) return setError(error.message.toLowerCase().includes("invalid") ? "Email ou mot de passe incorrect." : "Connexion impossible pour le moment. Réessayez.");
    onDone();
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <h1 className="text-lg font-semibold">{forgot ? "Mot de passe oublié" : "Connexion"}</h1>
      {info && <p className="rounded-md bg-muted px-3 py-2 text-sm">{info}</p>}
      <div className="space-y-1.5">
        <Label htmlFor="email">Email professionnel</Label>
        <Input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="prenom.nom@oddo.ma" />
      </div>
      {!forgot && (
        <div className="space-y-1.5">
          <Label htmlFor="password">Mot de passe</Label>
          <Input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
      )}
      {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
      <Button type="submit" className="w-full" disabled={busy}>
        {busy && <Loader2 className="animate-spin" />} {forgot ? "Recevoir le lien" : "Se connecter"}
      </Button>
      <button type="button" className="w-full text-center text-sm text-muted-foreground hover:text-foreground"
        onClick={() => { setForgot(!forgot); setError(null); setInfo(null); }}>
        {forgot ? "Retour à la connexion" : "Mot de passe oublié ?"}
      </button>
      {!forgot && <p className="text-xs text-muted-foreground">Pas encore de compte ? Demandez une invitation à l'administrateur.</p>}
    </form>
  );
}

function SetPasswordForm({ reason, onDone }: { reason: "invite" | "recovery"; onDone: () => void }) {
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (pw.length < 10) return setError("10 caractères minimum.");
    if (pw !== pw2) return setError("Les deux mots de passe ne sont pas identiques.");
    setBusy(true); setError(null);
    const { error } = await supabase()!.auth.updateUser({ password: pw });
    setBusy(false);
    if (error) return setError(error.message.toLowerCase().includes("weak") || error.message.toLowerCase().includes("password")
      ? "Mot de passe refusé : choisissez-en un plus long ou moins courant." : "Enregistrement impossible. Réessayez.");
    onDone();
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <h1 className="text-lg font-semibold">{reason === "invite" ? "Bienvenue ! Choisissez votre mot de passe" : "Nouveau mot de passe"}</h1>
      <p className="text-sm text-muted-foreground">Il vous servira à vous connecter à ODDO Séquences. 10 caractères minimum.</p>
      <div className="space-y-1.5">
        <Label htmlFor="pw">Mot de passe</Label>
        <Input id="pw" type="password" autoComplete="new-password" required value={pw} onChange={(e) => setPw(e.target.value)} />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="pw2">Confirmer</Label>
        <Input id="pw2" type="password" autoComplete="new-password" required value={pw2} onChange={(e) => setPw2(e.target.value)} />
      </div>
      {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
      <Button type="submit" className="w-full" disabled={busy}>{busy && <Loader2 className="animate-spin" />} Enregistrer et entrer</Button>
    </form>
  );
}
