"""Faux serveur IMAP minimal (TLS dès la connexion, comme le port 993).

Il implémente juste ce dont l'app a besoin : CAPABILITY, LOGIN, LIST, NOOP,
LOGOUT, APPEND, SELECT/EXAMINE, UID SEARCH (UID n:* / SINCE / ALL) et
UID FETCH (BODY.PEEK[]). Il enregistre si un message a été marqué comme lu,
pour vérifier que l'app ne le fait jamais.
"""
import re
import socketserver
from datetime import date, datetime, timezone
import ssl
import threading
from dataclasses import dataclass, field

from tests.fakes.certs import server_context
from tests.fakes.fake_smtp import free_port

_TOKEN_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\([^)]*\)|\{\d+\+?\}|\S+')


def _unquote(tok: str) -> str:
    if len(tok) >= 2 and tok[0] == '"' and tok[-1] == '"':
        return tok[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return tok


@dataclass
class FakeFolder:
    flags: list[str]
    uidvalidity: int = 1
    next_uid: int = 1
    messages: list[tuple[int, list[str], bytes]] = field(default_factory=list)  # (uid, flags, contenu)
    dates: dict[int, date] = field(default_factory=dict)  # date de réception (pour SEARCH SINCE)


class FakeImapServer:
    def __init__(self, username: str, password: str, folders: dict[str, list[str]] | None = None,
                 port: int | None = None):
        self.username, self.password = username, password
        if folders is None:
            folders = {"INBOX": [], "INBOX.Sent": ["\\Sent"], "INBOX.Junk": ["\\Junk"],
                       "INBOX.Drafts": ["\\Drafts"]}
        self.folders = {name: FakeFolder(flags=list(flags)) for name, flags in folders.items()}
        self.commands: list[str] = []  # noms des commandes reçues (jamais les arguments)
        self.port = port or free_port()
        self._server: socketserver.ThreadingTCPServer | None = None
        self._lock = threading.Lock()
        self.capabilities = "IMAP4rev1 SPECIAL-USE MOVE UIDPLUS"  # V2.20 : archivage

    # --- démarrage / arrêt ---------------------------------------------------
    def start(self):
        outer = self
        ctx = server_context()

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                outer._session(self.rfile, self.wfile)

        class TLSServer(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

            def get_request(self):
                sock, addr = super().get_request()
                return ctx.wrap_socket(sock, server_side=True), addr

        self._server = TLSServer(("127.0.0.1", self.port), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def deliver(self, folder: str, raw: bytes, when: date | None = None, flags=None) -> int:
        """Dépose un message dans un dossier (comme un email qui arrive)."""
        f = self.folders[folder]
        with self._lock:
            uid = f.next_uid
            f.next_uid += 1
            f.messages.append((uid, list(flags or []), raw))
            f.dates[uid] = when or datetime.now(timezone.utc).date()
        return uid

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    # --- protocole -----------------------------------------------------------
    def _session(self, rfile, wfile):
        def send(line: str):
            wfile.write(line.encode("utf-8") + b"\r\n")
            wfile.flush()

        send(f"* OK [CAPABILITY {self.capabilities}] Fake IMAP pret")
        authed = False
        selected: FakeFolder | None = None
        readonly = False
        while True:
            try:
                raw = rfile.readline()
            except (ssl.SSLError, OSError):
                return
            if not raw:
                return
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            parts = line.split(" ", 2)
            if len(parts) < 2:
                send("* BAD commande illisible")
                continue
            tag, cmd = parts[0], parts[1].upper()
            args = _TOKEN_RE.findall(parts[2]) if len(parts) > 2 else []
            self.commands.append(cmd)

            if cmd == "CAPABILITY":
                send(f"* CAPABILITY {self.capabilities}")
                send(f"{tag} OK CAPABILITY termine")
            elif cmd == "NOOP":
                send(f"{tag} OK NOOP termine")
            elif cmd == "LOGIN":
                user, pw = (_unquote(a) for a in args[:2])
                if user == self.username and pw == self.password:
                    authed = True
                    send(f"{tag} OK LOGIN termine")
                else:
                    send(f"{tag} NO [AUTHENTICATIONFAILED] Identifiants invalides")
            elif cmd == "LOGOUT":
                send("* BYE au revoir")
                send(f"{tag} OK LOGOUT termine")
                return
            elif not authed:
                send(f"{tag} NO non authentifie")
            elif cmd == "LIST":
                for name, folder in self.folders.items():
                    flags = " ".join(["\\HasNoChildren", *folder.flags])
                    send(f'* LIST ({flags}) "." "{name}"')
                send(f"{tag} OK LIST termine")
            elif cmd == "APPEND":
                self._append(tag, args, rfile, send)
            elif cmd in ("SELECT", "EXAMINE"):
                selected = self.folders.get(_unquote(args[0]))
                readonly = cmd == "EXAMINE"
                if selected is None:
                    send(f"{tag} NO dossier inconnu")
                    continue
                send(f"* {len(selected.messages)} EXISTS")
                send(f"* OK [UIDVALIDITY {selected.uidvalidity}] UIDs valides")
                send(f"* OK [UIDNEXT {selected.next_uid}] prochain UID")
                send(f"{tag} OK [{'READ-ONLY' if readonly else 'READ-WRITE'}] {cmd} termine")
            elif cmd == "UID" and selected is not None and args and args[0].upper() == "SEARCH":
                send("* SEARCH " + " ".join(str(u) for u in self._search(selected, args[1:])))
                send(f"{tag} OK SEARCH termine")
            elif cmd == "UID" and selected is not None and args and args[0].upper() == "FETCH":
                wanted = self._uid_set(selected, args[1])
                what = " ".join(args[2:]).upper()
                peek = "PEEK" in what
                for seq, (uid, flags, data) in enumerate(selected.messages, start=1):
                    if uid in wanted:
                        if "HEADER.FIELDS" in what:
                            # V2.4 : liste de la boîte mail -> drapeaux, taille et en-têtes seulement
                            head = data.split(b"\r\n\r\n", 1)[0].split(b"\n\n", 1)[0] + b"\r\n\r\n"
                            wfile.write(f"* {seq} FETCH (UID {uid} FLAGS ({' '.join(flags)}) RFC822.SIZE {len(data)} "
                                        f"BODY[HEADER.FIELDS (FROM)] {{{len(head)}}}\r\n".encode() + head + b")\r\n")
                            continue
                        if not peek and "\\Seen" not in flags:
                            flags.append("\\Seen")  # un FETCH BODY[] sans PEEK marque comme lu
                        wfile.write(f"* {seq} FETCH (UID {uid} BODY[] {{{len(data)}}}\r\n".encode() + data + b")\r\n")
                wfile.flush()
                send(f"{tag} OK FETCH termine")
            elif cmd == "CREATE":
                name = _unquote(args[0])
                with self._lock:
                    self.folders.setdefault(name, FakeFolder(flags=[], uidvalidity=len(self.folders) + 1))
                send(f"{tag} OK CREATE termine")
            elif cmd == "SUBSCRIBE":
                send(f"{tag} OK SUBSCRIBE termine")
            elif cmd == "UID" and selected is not None and args and args[0].upper() in ("MOVE", "COPY") \
                    and (args[0].upper() == "COPY" or "MOVE" in self.capabilities):
                if readonly and args[0].upper() == "MOVE":
                    send(f"{tag} NO dossier en lecture seule")
                    continue
                dest = self.folders.get(_unquote(args[2]))
                if dest is None:
                    send(f"{tag} NO [TRYCREATE] dossier inconnu")
                    continue
                wanted = self._uid_set(selected, args[1])
                moved = []
                with self._lock:
                    for item in list(selected.messages):
                        if item[0] in wanted:
                            new_uid = dest.next_uid
                            dest.next_uid += 1
                            dest.messages.append((new_uid, list(item[1]), item[2]))
                            dest.dates[new_uid] = selected.dates.get(item[0], date.today())
                            moved.append((item[0], new_uid))
                            if args[0].upper() == "MOVE":
                                selected.messages.remove(item)
                src = ",".join(str(a) for a, _ in moved)
                dst = ",".join(str(b) for _, b in moved)
                send(f"{tag} OK [COPYUID {dest.uidvalidity} {src} {dst}] {args[0].upper()} termine")
            elif cmd == "UID" and selected is not None and args and args[0].upper() == "STORE":
                if readonly:
                    send(f"{tag} NO dossier en lecture seule")
                    continue
                wanted = self._uid_set(selected, args[1])
                new_flags = " ".join(args[3:]).strip("()").split()
                remove = args[2].startswith("-")
                for uid, flags, _ in selected.messages:
                    if uid in wanted:
                        if remove:
                            flags[:] = [f for f in flags if f not in new_flags]
                        else:
                            flags.extend(f for f in new_flags if f not in flags)
                send(f"{tag} OK STORE termine")
            elif cmd == "STATUS":
                folder = self.folders.get(_unquote(args[0]))
                if folder is None:
                    send(f"{tag} NO dossier inconnu")
                    continue
                unseen = sum(1 for _, flags, _ in folder.messages if "\\Seen" not in flags)
                send(f'* STATUS "{_unquote(args[0])}" (UNSEEN {unseen})')
                send(f"{tag} OK STATUS termine")
            elif cmd == "UID" and selected is not None and args and args[0].upper() == "EXPUNGE":
                wanted = self._uid_set(selected, args[1])
                with self._lock:
                    selected.messages[:] = [m for m in selected.messages if not (m[0] in wanted and "\\Deleted" in m[1])]
                send(f"{tag} OK EXPUNGE termine")
            else:
                send(f"{tag} BAD commande non geree par le faux serveur : {cmd}")

    @staticmethod
    def _uid_set(folder: FakeFolder, spec: str) -> set[int]:
        uids = {u for u, _, _ in folder.messages}
        out = set()
        for part in spec.split(","):
            if ":" in part:
                a, b = part.split(":")
                lo = int(a)
                hi = max(uids, default=0) if b == "*" else int(b)
                out |= {u for u in uids if lo <= u <= hi}
                if b == "*" and uids:
                    out.add(max(uids))  # règle IMAP : « n:* » inclut toujours le dernier message
            else:
                out.add(int(part))
        return out & uids

    def _search(self, folder: FakeFolder, criteria: list[str]) -> list[int]:
        crit = [c.upper() for c in criteria]
        if not crit or crit[0] == "ALL":
            return [u for u, _, _ in folder.messages]
        if crit[0] == "UID":
            return sorted(self._uid_set(folder, criteria[1]))
        if crit[0] == "HEADER" and len(criteria) >= 3:
            field, value = criteria[1].lower(), _unquote(criteria[2]).lower()
            out = []
            for u, _, data in folder.messages:
                head = data.split(b"\r\n\r\n", 1)[0].decode("utf-8", "replace").lower()
                if any(line.startswith(field + ":") and value in line for line in head.replace("\r\n", "\n").split("\n")):
                    out.append(u)
            return out
        if crit[0] == "SINCE":
            since = datetime.strptime(criteria[1], "%d-%b-%Y").date()
            found = [(u, data) for u, _, data in folder.messages if folder.dates.get(u, date.min) >= since]
            rest = criteria[2:]
            while rest:  # V3.4.4 : critères suivants (OR / FROM / TO / CC / SUBJECT), tous à respecter
                test, rest = self._criterion(rest)
                found = [(u, d) for u, d in found if test(d)]
            return [u for u, _ in found]
        return []

    def _criterion(self, toks):
        """Un critère IMAP en notation préfixée ; renvoie (test(données) -> bool, reste)."""
        head = toks[0].upper()
        if head == "OR":
            a, rest = self._criterion(toks[1:])
            b, rest = self._criterion(rest)
            return (lambda d: a(d) or b(d)), rest
        field, value = head.lower(), _unquote(toks[1]).lower()

        def test(data):
            heads = data.split(b"\r\n\r\n", 1)[0].decode("utf-8", "replace").lower().replace("\r\n", "\n")
            return any(line.startswith(field + ":") and value in line for line in heads.split("\n"))
        return test, toks[2:]

    def _append(self, tag, args, rfile, send):
        folder_name = _unquote(args[0])
        flags = []
        literal = args[-1]
        if len(args) >= 2 and args[1].startswith("("):
            flags = args[1].strip("()").split()
        m = re.match(r"\{(\d+)\+?\}", literal)
        if not m:
            send(f"{tag} BAD APPEND sans litteral")
            return
        size = int(m.group(1))
        if not literal.endswith("+}"):
            send("+ Pret pour le contenu")
        data = rfile.read(size)
        rfile.readline()  # fin de ligne après le littéral
        folder = self.folders.get(folder_name)
        if folder is None:
            send(f"{tag} NO [TRYCREATE] dossier inconnu")
            return
        with self._lock:
            uid = folder.next_uid
            folder.next_uid += 1
            folder.messages.append((uid, flags, data))
        send(f"{tag} OK [APPENDUID {folder.uidvalidity} {uid}] APPEND termine")
