"""Décodage des noms de dossiers IMAP (« UTF-7 modifié », RFC 3501 §5.1.3).

Les serveurs IMAP n'envoient pas « Éléments envoyés » tel quel mais
« &AMk-l&AOk-ments envoy&AOk-s ». On décode pour l'AFFICHAGE uniquement :
dans les commandes IMAP, on réutilise toujours le nom brut renvoyé par le serveur.
"""
import base64


def decode(name: str) -> str:
    out, i = [], 0
    while i < len(name):
        ch = name[i]
        if ch != "&":
            out.append(ch)
            i += 1
            continue
        end = name.find("-", i)
        if end == -1:  # nom malformé : on le laisse tel quel
            out.append(name[i:])
            break
        chunk = name[i + 1:end]
        if chunk == "":
            out.append("&")  # « &- » représente le caractère &
        else:
            b64 = chunk.replace(",", "/")
            b64 += "=" * (-len(b64) % 4)
            out.append(base64.b64decode(b64).decode("utf-16-be"))
        i = end + 1
    return "".join(out)


def encode(name: str) -> str:
    """Inverse de decode (utile pour les tests et les noms saisis à la main)."""
    out, buf = [], []

    def flush():
        if buf:
            raw = "".join(buf).encode("utf-16-be")
            out.append("&" + base64.b64encode(raw).decode().rstrip("=").replace("/", ",") + "-")
            buf.clear()

    for ch in name:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)
