// V3.7 : champ de destinataires comme une messagerie : chaque adresse devient une pastille,
// et la saisie propose la fin de l'adresse (« yassine » → yassine.laoud@…) d'après vos contacts,
// les gens à qui vous avez écrit, ceux qui vous ont écrit, et vos collègues.
import { useQuery } from "@tanstack/react-query";
import { Building2, User, Users, X } from "lucide-react";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

import { api, type AddressSuggestion } from "@/lib/api";
import { cn } from "@/lib/utils";

const EMAIL = /^[^\s@<>,;]+@[^\s@<>,;]+\.[^\s@<>,;]{2,}$/;
const names = new Map<string, string>();  // adresse → nom, retenu pour l'affichage des pastilles

export const splitAddresses = (v: string | undefined) =>
  (v ?? "").split(/[,;]+/).map((x) => x.trim().toLowerCase()).filter(Boolean);
export const joinAddresses = (a: string[]) => a.join(", ");

/** « Yassine Laoud <yassine@x.ma>, autre@y.ma ; z@w.ma » → adresses (avec les noms retenus). */
function parse(text: string): string[] {
  const out: string[] = [];
  for (const part of text.split(/[,;\n]+/)) {
    const m = part.match(/^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$/);
    if (m) {
      const email = m[2].trim().toLowerCase();
      if (m[1].trim()) names.set(email, m[1].trim());
      out.push(email);
    } else {
      out.push(...part.trim().split(/\s+/).map((x) => x.toLowerCase()).filter(Boolean));
    }
  }
  return out;
}

export type RecipientInputHandle = { focus: () => void };

export const RecipientInput = forwardRef<RecipientInputHandle, {
  label: string; value: string[]; onChange: (v: string[]) => void; draft: string; onDraft: (v: string) => void;
  exclude?: string[]; placeholder?: string; trailing?: React.ReactNode; className?: string;
}>(function RecipientInput({ label, value, onChange, draft, onDraft, exclude = [], placeholder, trailing, className }, ref) {
  const input = useRef<HTMLInputElement>(null);
  useImperativeHandle(ref, () => ({ focus: () => input.current?.focus() }));
  const [focused, setFocused] = useState(false);
  const [active, setActive] = useState(0);
  const [q, setQ] = useState("");
  useEffect(() => { const t = setTimeout(() => setQ(draft.trim()), 150); return () => clearTimeout(t); }, [draft]);
  const taken = [...value, ...exclude];
  const { data } = useQuery({
    queryKey: ["mail-suggest", q.toLowerCase()], queryFn: () => api.mailSuggest(q),
    enabled: focused && q.length >= 2 && !q.includes(","), staleTime: 30_000,
  });
  const items = (data?.items ?? []).filter((s) => !taken.includes(s.email));
  const open = focused && q.length >= 2 && items.length > 0 && draft.trim().length >= 2;
  useEffect(() => setActive(0), [q]);

  const add = (emails: string[]) => {
    const fresh = emails.filter((e) => e && !value.includes(e));
    if (fresh.length) onChange([...value, ...fresh]);
    onDraft("");
  };
  const pick = (s: AddressSuggestion) => { if (s.name) names.set(s.email, s.name); add([s.email]); input.current?.focus(); };
  const commit = () => { if (draft.trim()) add(parse(draft)); };

  return (
    <div className={cn("relative flex items-start gap-2 border-b px-4", className)}>
      <span className="w-12 shrink-0 py-2.5 text-sm text-muted-foreground">{label}</span>
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1 py-1.5" onClick={() => input.current?.focus()}>
        {value.map((e) => {
          const ok = EMAIL.test(e);
          const name = names.get(e);
          return (
            <span key={e} title={ok ? e : `${e} : adresse invalide`}
              className={cn("inline-flex max-w-full items-center gap-1 rounded-md border py-0.5 pl-2 pr-0.5 text-sm",
                ok ? "bg-muted/60" : "border-destructive/60 bg-destructive/10 text-destructive")}
              onDoubleClick={() => { onChange(value.filter((x) => x !== e)); onDraft(e); input.current?.focus(); }}>
              <span className="truncate">{name ?? e}</span>
              <button type="button" className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground" aria-label={`Retirer ${e}`}
                onClick={(ev) => { ev.stopPropagation(); onChange(value.filter((x) => x !== e)); }}><X className="size-3.5" /></button>
            </span>
          );
        })}
        <input ref={input} value={draft} aria-label={label === "À" ? "Destinataires" : label}
          role="combobox" aria-expanded={open} aria-autocomplete="list"
          className="h-7 min-w-[6rem] flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          placeholder={value.length ? "" : placeholder}
          onChange={(e) => {
            const v = e.target.value;
            if (/[,;]\s*$/.test(v) && v.replace(/[,;\s]/g, "")) { add(parse(v)); return; }  // « , » ou « ; » : la pastille se forme
            onDraft(v);
          }}
          onPaste={(e) => {
            const t = e.clipboardData.getData("text");
            if (/[,;\n<]/.test(t) || t.trim().split(/\s+/).length > 1) { e.preventDefault(); add(parse(`${draft}${t}`)); }
          }}
          onFocus={() => setFocused(true)}
          onBlur={() => { setFocused(false); commit(); }}
          onKeyDown={(e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === "Enter") return;  // envoi : géré par le formulaire
            if (open && e.key === "ArrowDown") { e.preventDefault(); setActive((i) => (i + 1) % items.length); return; }
            if (open && e.key === "ArrowUp") { e.preventDefault(); setActive((i) => (i - 1 + items.length) % items.length); return; }
            if (e.key === "Enter" || (e.key === "Tab" && draft.trim())) {
              if (open && items[active]) { e.preventDefault(); pick(items[active]); return; }
              if (draft.trim()) { e.preventDefault(); commit(); }
              return;
            }
            if (e.key === " " && EMAIL.test(draft.trim())) { e.preventDefault(); commit(); return; }
            if (e.key === "Backspace" && !draft && value.length) { onChange(value.slice(0, -1)); return; }
            if (e.key === "Escape" && open) { e.stopPropagation(); setFocused(false); }
          }} />
      </div>
      {trailing && <div className="flex shrink-0 items-center gap-2 py-2.5">{trailing}</div>}
      {open && (
        <ul role="listbox" className="absolute left-14 right-4 top-full z-20 mt-1 max-h-72 overflow-y-auto rounded-lg border bg-popover p-1 shadow-lg">
          {items.map((s, i) => (
            <li key={s.email} role="option" aria-selected={i === active}
              className={cn("flex cursor-pointer items-center gap-3 rounded-md px-2.5 py-2", i === active && "bg-accent")}
              onMouseEnter={() => setActive(i)} onMouseDown={(e) => { e.preventDefault(); pick(s); }}>
              <span className="grid size-7 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground">
                {s.kind === "team" ? <Users className="size-3.5" /> : s.company ? <Building2 className="size-3.5" /> : <User className="size-3.5" />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm">{s.name ?? s.email}{s.company && <span className="text-muted-foreground"> · {s.company}</span>}</span>
                {s.name && <span className="block truncate text-xs text-muted-foreground">{s.email}</span>}
              </span>
              {s.kind === "team" && <span className="text-[11px] text-muted-foreground">Équipe</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
});
