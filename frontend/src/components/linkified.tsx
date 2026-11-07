// V2.11 : dans un email affiché en texte, les adresses web interminables deviennent un lien
// court « nom du site ↗ » (l'adresse complète reste visible au survol).
import { ExternalLink, Image as ImageIcon } from "lucide-react";
import { Fragment } from "react";

const URL_RE = /(https?:\/\/[^\s<>()[\]"'{}]+)/g;
const IMG_RE = /\.(png|jpe?g|gif|webp|svg)(\?|$)/i;

function host(url: string) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return "lien"; }
}

export function Linkified({ text }: { text: string }) {
  const parts = text.split(URL_RE);
  return (
    <>
      {parts.map((p, i) => {
        if (i % 2 === 0) return <Fragment key={i}>{p}</Fragment>;
        const trail = p.match(/[.,;:!?]+$/)?.[0] ?? "";
        const url = trail ? p.slice(0, -trail.length) : p;
        const img = IMG_RE.test(url);
        return (
          <Fragment key={i}>
            <a href={url} target="_blank" rel="noreferrer noopener" title={url}
              className="mx-0.5 inline-flex max-w-full items-center gap-1 rounded-md border bg-muted/50 px-1.5 py-px align-baseline text-xs font-medium text-primary no-underline hover:bg-accent">
              {img ? <ImageIcon className="size-3 shrink-0" /> : <ExternalLink className="size-3 shrink-0" />}
              <span className="truncate">{img ? "image" : host(url)}</span>
            </a>
            {trail}
          </Fragment>
        );
      })}
    </>
  );
}
