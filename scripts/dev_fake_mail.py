"""Bac à sable : faux serveurs SMTP et IMAP sur votre PC, pour essayer l'app sans
toucher la vraie boîte o.douiri@oddo.ma. Rien ne sort sur Internet.

Utilisation (deux fenêtres de commande, depuis le dossier du projet) :

  1) .venv\\Scripts\\python -m pip install -r requirements-dev.txt   (une seule fois)
  2) .venv\\Scripts\\python -m scripts.dev_fake_mail
  3) dans une autre fenêtre :
       set ODDO_EXTRA_CA_FILE=tests\\fixtures\\certs\\ca.pem
       set ODDO_DATA_DIR=data_bac_a_sable
       .venv\\Scripts\\python -m app.launcher

Puis dans Réglages : SMTP 127.0.0.1 / 2465 / SSL, IMAP 127.0.0.1 / 2993,
identifiant o.douiri@oddo.ma, mot de passe « bac-a-sable ».
"""
import time

from tests.fakes.fake_imap import FakeImapServer
from tests.fakes.fake_smtp import FakeSmtpServer

USER, PASSWORD = "o.douiri@oddo.ma", "bac-a-sable"


def main():
    smtp = FakeSmtpServer(USER, PASSWORD, mode="ssl", port=2465).start()
    imap = FakeImapServer(USER, PASSWORD, port=2993).start()
    print("Faux SMTP : 127.0.0.1:2465 (SSL)   Faux IMAP : 127.0.0.1:2993 (SSL)")
    print(f"Identifiant : {USER}   Mot de passe : {PASSWORD}")
    print("Ctrl+C pour arrêter.\n")
    seen = 0
    try:
        while True:
            time.sleep(1)
            for m in smtp.messages[seen:]:
                subject = next((l for l in m.data.decode("utf-8", "replace").splitlines()
                                if l.lower().startswith("subject:")), "Subject: ?")
                print(f"[SMTP] reçu pour {', '.join(m.rcpt_tos)} | {subject}")
            seen = len(smtp.messages)
    except KeyboardInterrupt:
        pass
    finally:
        smtp.stop()
        imap.stop()


if __name__ == "__main__":
    main()
