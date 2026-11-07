// V2.19 : un email reçu s'affiche comme dans Outlook : mise en forme, photos intégrées,
// pièces jointes ouvrables. Sécurité : le HTML est rendu dans un cadre isolé (aucun script,
// aucun formulaire) ; les images venant d'Internet sont bloquées tant qu'on ne les demande pas
// (elles servent souvent à savoir si l'email a été ouvert).
import { Download, Eye, FileText, Image as ImageIcon, Paperclip } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import type { MailAttachment } from "@/lib/api";
import { cn } from "@/lib/utils";

function srcdoc(html: string, remote: boolean) {
  const ext = remote ? " https: http:" : "";
  return `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data: 'self'${ext}; style-src 'unsafe-inline'${ext}; font-src data:${ext}">
<base target="_blank">
<style>html,body{margin:0;padding:0;background:#fff}body{padding:4px 2px;font:14px/1.55 Inter,"Segoe UI",system-ui,sans-serif;color:#1f2430;overflow-wrap:anywhere}img{max-width:100%;height:auto}table{max-width:100%!important}pre{white-space:pre-wrap}</style>
</head><body>${html}</body></html>`;
}

export function MailHtml({ html, remoteImages }: { html: string; remoteImages: boolean }) {
  const ref = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(200);
  const [showRemote, setShowRemote] = useState(false);

  useEffect(() => {
    const frame = ref.current;
    if (!frame) return;
    let ro: ResizeObserver | null = null;
    const fit = () => {
      const doc = frame.contentDocument;
      if (doc?.documentElement) setHeight(Math.max(80, doc.documentElement.scrollHeight + 4));
    };
    const onLoad = () => {
      fit();
      const body = frame.contentDocument?.body;
      if (body && "ResizeObserver" in window) { ro = new ResizeObserver(fit); ro.observe(body); }
    };
    frame.addEventListener("load", onLoad);
    return () => { frame.removeEventListener("load", onLoad); ro?.disconnect(); };
  }, [html, showRemote]);

  return (
    <div className="space-y-2">
      {remoteImages && !showRemote && (
        <div className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          <ImageIcon className="size-3.5" />Images venant d'Internet masquées (elles peuvent servir à savoir si vous avez ouvert l'email).
          <Button size="sm" variant="outline" className="ml-auto h-7" onClick={() => setShowRemote(true)}><Eye /> Afficher les images</Button>
        </div>
      )}
      <iframe ref={ref} title="Contenu de l'email" srcDoc={srcdoc(html, showRemote)} style={{ height }}
        sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox"
        className="w-full rounded-md border bg-white" />
    </div>
  );
}

function size(n: number) {
  return n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1).replace(".", ",")} Mo` : `${Math.max(1, Math.round(n / 1024))} Ko`;
}

export function MailAttachments({ items }: { items: MailAttachment[] }) {
  if (!items.length) return null;
  const images = items.filter((a) => a.type.startsWith("image/") && a.viewable);
  return (
    <div className="space-y-2 border-t pt-4">
      <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground"><Paperclip className="size-3.5" />{items.length} pièce{items.length > 1 ? "s" : ""} jointe{items.length > 1 ? "s" : ""}</p>
      {images.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {images.map((a) => (
            <a key={a.index} href={a.url} target="_blank" rel="noreferrer" title={`Ouvrir ${a.name}`}
              className="block overflow-hidden rounded-md border bg-muted/30 transition-shadow hover:shadow-md">
              <img src={a.url} alt={a.name} loading="lazy" className="h-28 w-auto max-w-[14rem] object-cover" />
            </a>
          ))}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {items.map((a) => (
          <div key={a.index} className="flex max-w-full items-center gap-2 rounded-md border bg-card px-2.5 py-1.5 text-sm">
            {a.type.startsWith("image/") ? <ImageIcon className="size-4 shrink-0 text-muted-foreground" /> : <FileText className="size-4 shrink-0 text-muted-foreground" />}
            {a.viewable
              ? <a href={a.url} target="_blank" rel="noreferrer" className="truncate hover:text-primary hover:underline" title="Ouvrir">{a.name}</a>
              : <a href={`${a.url}&download=1`} download={a.name} className="truncate hover:text-primary hover:underline" title="Télécharger puis ouvrir">{a.name}</a>}
            <span className="shrink-0 text-xs text-muted-foreground">{size(a.size)}</span>
            <a href={`${a.url}&download=1`} download={a.name} title="Télécharger" aria-label={`Télécharger ${a.name}`}
              className={cn("shrink-0 text-muted-foreground hover:text-primary")}><Download className="size-3.5" /></a>
          </div>
        ))}
      </div>
    </div>
  );
}
