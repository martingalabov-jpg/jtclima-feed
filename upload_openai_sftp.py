"""Upload feed/jtclima_openai_products.csv.gz to the OpenAI Ads feed's SFTP root (same filename every run,
overwritten in place - OpenAI processes every file in the root as the full catalog). Needs paramiko.

Settings come from env vars (GitHub Actions secrets):
  OPENAI_SFTP_URI          connection URI returned by POST /v1/feeds/{feed_id}/sftp_access (sftp://user@host:port)
  OPENAI_SFTP_PASSWORD     password from the same call (password auth), or
  OPENAI_SFTP_PRIVATE_KEY  private key matching the ssh_public_key sent to OpenAI (key auth)
  OPENAI_SFTP_HOST_KEY     optional, "ssh-ed25519 AAAA..." to pin the server key (else trusted on first use)"""
import base64, io, os, sys, urllib.parse
import paramiko

SRC = "feed/jtclima_openai_products.csv.gz"
DEST = "jtclima_openai_products.csv.gz"


def private_key(text):
    for cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            return cls.from_private_key(io.StringIO(text))
        except paramiko.SSHException:
            continue
    raise SystemExit("OPENAI_SFTP_PRIVATE_KEY is not a readable Ed25519 / ECDSA / RSA private key")


uri = urllib.parse.urlsplit(os.environ["OPENAI_SFTP_URI"].strip())
if uri.scheme not in ("sftp", "ssh") or not uri.hostname or not uri.username:
    raise SystemExit("OPENAI_SFTP_URI must look like sftp://user@host:port")
password = os.environ.get("OPENAI_SFTP_PASSWORD") or urllib.parse.unquote(uri.password or "") or None
key_text = os.environ.get("OPENAI_SFTP_PRIVATE_KEY", "").strip()
if not password and not key_text:
    raise SystemExit("Set OPENAI_SFTP_PASSWORD or OPENAI_SFTP_PRIVATE_KEY")
if not os.path.getsize(SRC):
    raise SystemExit("%s is empty - not uploading" % SRC)

client = paramiko.SSHClient()
pinned = os.environ.get("OPENAI_SFTP_HOST_KEY", "").split()
if len(pinned) >= 2:
    key = paramiko.PKey.from_type_string(pinned[0], base64.b64decode(pinned[1]))
    port = uri.port or 22
    client.get_host_keys().add(uri.hostname if port == 22 else "[%s]:%d" % (uri.hostname, port), pinned[0], key)
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
else:
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(uri.hostname, port=uri.port or 22, username=urllib.parse.unquote(uri.username),
               password=password, pkey=private_key(key_text) if key_text else None,
               look_for_keys=False, allow_agent=False, timeout=60)
server_key = client.get_transport().get_remote_server_key()
print("Connected to %s (host key %s %s)" % (uri.hostname, server_key.get_name(), server_key.get_base64()))

sftp = client.open_sftp()
if uri.path.strip("/"):
    sftp.chdir(uri.path)
attrs = sftp.put(SRC, DEST)  # confirm=True: raises if the remote size differs
sftp.close()
client.close()
print("Uploaded %s -> %s%s (%d bytes)" % (SRC, uri.path.rstrip("/") + "/" if uri.path.strip("/") else "", DEST,
                                         attrs.st_size))
