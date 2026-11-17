"""Run the archival Lambda against a local PostgreSQL with S3 mocked."""
import gzip, io, json, os, sys, hashlib
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src", "requests_backup_export"))

UPLOADS = {}          # key -> bytes

class FakeS3:
    def upload_file(self, path, bucket, key):
        with open(path, "rb") as fh:
            UPLOADS[key] = fh.read()
    def get_object(self, **kw): raise FileNotFoundError("NoSuchKey")
    def put_object(self, **kw): pass

class FakeSSM:
    def get_parameter(self, **kw):
        return {"Parameter": {"Value": json.dumps({
            "HOST": "127.0.0.1", "USERNAME": "postgres", "PASSWORD": "",
            "DATABASE NAME": "saayamtest", "PORT": "5433", "SSL": "false"})}}

os.environ.update(BUCKET="saayam-virginia-archive", STATE_STORE="postgres",
                  COMPRESS="none", STREAM="backup", DB_PARAM="/fake")

with patch("boto3.client", lambda svc, **kw: FakeS3() if svc == "s3" else FakeSSM()):
    import lambda_function as fn

class Ctx:  aws_request_id = "local-test"

def show(title): print("\n" + "=" * 70 + "\n" + title + "\n" + "=" * 70)

def run(event=None):
    with patch.object(fn, "s3", FakeS3()), patch.object(fn, "ssm", FakeSSM()):
        return fn.handler(event or {"triggered_by": "local"}, Ctx())

def body(key):
    raw = UPLOADS[key]
    return gzip.decompress(raw).decode() if key.endswith(".gz") else raw.decode()

if __name__ == "__main__":
    show("RUN 1  full export from initial_value")
    r1 = run(); print(json.dumps(r1, indent=2))
    csvtext = body(r1["key"])
    lines = csvtext.strip().split("\n")
    print(f"\nheader ({len(lines[0].split(','))} columns):\n  " + lines[0])
    print(f"\nfirst row:\n  " + lines[1])
    print(f"\nrows in file: {len(lines) - 1}")

    show("RUN 2  immediately after, should find nothing")
    print(json.dumps(run(), indent=2))

    show("RUN 3  idempotency: same explicit window twice")
    ev = {"triggered_by": "local", "from": "2000-01-01 00:00:00", "to": "2026-11-01 23:00:00"}
    a = run(ev); h1 = hashlib.sha256(UPLOADS[a["key"]]).hexdigest()
    b = run(ev); h2 = hashlib.sha256(UPLOADS[b["key"]]).hexdigest()
    print(f"key 1 : {a['key']}\nkey 2 : {b['key']}\nsame key   : {a['key'] == b['key']}")
    print(f"sha 1 : {h1[:16]}\nsha 2 : {h2[:16]}\nsame bytes : {h1 == h2}")
