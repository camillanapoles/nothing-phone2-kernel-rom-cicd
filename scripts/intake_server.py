#!/usr/bin/env python3
"""Temporary, local-only artifact intake for the Pong CI/CD collection.

Streams one raw browser upload to .intake/, computes SHA256, and writes a
non-canonical candidate object. It never edits objects/, runs CI, or authorizes
staging/release. No third-party packages are required.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path, PureWindowsPath
import re
import secrets
import shutil
import tempfile
import textwrap
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

SCHEMA = "pong-intake-candidate/1"
MAX_METADATA = 4096


def load_catalog(root: Path) -> list[dict]:
    catalog: list[dict] = []
    rom = json.loads((root / "objects/rom-artifacts.json").read_text())
    for item in rom["variants"]:
        catalog.append({
            "intake_id": f"rom:{item['id']}", "asset_id": item["id"],
            "group": "ROM", "kind": f"rom/{item['id']}", "required": True,
            "pin": f"{rom['version']} / {rom['build']}",
            "expected_filename": item["filename"], "expected_sha256": item["sha256"],
            "source": "objects/rom-artifacts.json", "upload_allowed": True,
            "reason": "The SHA256 is pinned; a match is integrity evidence, not device compatibility evidence.",
        })

    plan = json.loads((root / "objects/kernel-build-plan.json").read_text())
    for item in plan["build"]["patch_set"]:
        if not item.get("file") or not item.get("sha256"):
            continue
        catalog.append({
            "intake_id": f"kernel-patch:{item['id']}", "asset_id": item["id"],
            "group": "Kernel patch", "kind": "kernel/patch", "required": True,
            "pin": plan["source"]["pin"], "expected_filename": item["file"],
            "expected_sha256": item["sha256"], "source": "objects/kernel-build-plan.json",
            "upload_allowed": True, "reason": "Patch applicability is still proven separately without force or fuzz.",
        })

    workflow = (root / ".github/workflows/pong-cicd.yml").read_text()
    match = re.search(
        r"cat > collection/manifests/asset-registry\.json <<'JSON'\n(.*?)\n\s*JSON",
        workflow, re.S,
    )
    if not match:
        raise RuntimeError("Runtime asset registry was not found in the single workflow")
    registry = json.loads(textwrap.dedent(match.group(1)))
    for item in registry["assets"]:
        private = item["kind"].startswith("private/")
        device_only = item["kind"] == "system/webview"
        allowed = not private and not device_only
        reason = item.get("reason", "Review provenance and compatibility before promotion.")
        if private:
            reason = "Private key material is forbidden in this intake, Git, logs, and artifacts."
        elif device_only:
            reason = "This item requires redacted on-device evidence, not a substitute package upload."
        catalog.append({
            "intake_id": f"stack:{item['id']}", "asset_id": item["id"],
            "group": "Install stack", "kind": item["kind"],
            "required": item["required"], "pin": item.get("pin"),
            "expected_filename": item.get("filename"), "expected_sha256": item.get("sha256"),
            "source": ".github/workflows/pong-cicd.yml runtime asset registry",
            "upload_allowed": allowed, "reason": reason,
        })
    ids = [entry["intake_id"] for entry in catalog]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate intake identifiers")
    return catalog


def intake_token(root: Path) -> str:
    configured = os.environ.get("INTAKE_TOKEN")
    if configured:
        if len(configured) < 16:
            raise RuntimeError("INTAKE_TOKEN must contain at least 16 characters")
        return configured
    path = root / ".intake/token"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        token = path.read_text().strip()
        if len(token) >= 16:
            return token
    token = secrets.token_urlsafe(24)
    path.write_text(token + "\n")
    path.chmod(0o600)
    return token


def safe_filename(value: str) -> str:
    if not value or len(value) > 180 or value in {".", ".."}:
        raise ValueError("invalid filename")
    if "/" in value or "\\" in value or PureWindowsPath(value).name != value:
        raise ValueError("filename must not contain a path")
    if any(ord(char) < 32 for char in value) or not re.fullmatch(r"[A-Za-z0-9._+() @-]+", value):
        raise ValueError("filename contains unsupported characters")
    return value


class UploadError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


HTML = r"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pong · intake de artefatos</title><style>
:root{color-scheme:dark;--bg:#0b1017;--panel:#131c27;--line:#2c3a49;--text:#e8eef5;--muted:#a7b5c4;--accent:#64d2ff;--warn:#ffcf66}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,sans-serif}main{max-width:880px;margin:auto;padding:32px 18px 60px}h1{font-size:1.8rem;margin-bottom:.3rem}h2{font-size:1.1rem;margin-top:2rem}.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;margin-top:18px}.warning{border-color:#80652d;color:var(--warn)}label{display:block;font-weight:650;margin:14px 0 6px}input,select,textarea,button{width:100%;font:inherit;border-radius:8px;border:1px solid var(--line);padding:11px;background:#0d1520;color:var(--text)}textarea{min-height:76px;resize:vertical}button{margin-top:18px;background:#14536b;border-color:#267a9b;font-weight:700;cursor:pointer}button:disabled{opacity:.55;cursor:wait}.muted,small{color:var(--muted)}code,pre{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#0b121b;border:1px solid var(--line);padding:12px;border-radius:8px;max-height:360px;overflow:auto}progress{width:100%;height:20px;margin-top:14px}#result{overflow-wrap:anywhere}a{color:var(--accent)}.row{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:650px){.row{grid-template-columns:1fr}}
</style></head><body><main>
<h1>Pong · intake temporária</h1><p class="muted">Arquivo → SHA256 → objeto candidato. Streaming no servidor; nenhum binário entra no Git.</p>
<div class="panel warning"><strong>Não envie <code>keybox.xml</code>, chaves, tokens, credenciais ou dados pessoais.</strong><br>Upload não altera <code>objects/</code>, não dispara CI e não autoriza teste, flash, staging ou release. Todo item permanece em revisão.</div>
<div class="panel"><label for="asset">Componente orientado pelos contratos atuais</label><select id="asset"></select><div id="details" class="muted" style="margin-top:12px"></div>
<label for="file">Arquivo</label><input id="file" type="file">
<div class="row"><div><label for="source">URL de origem oficial (opcional)</label><input id="source" type="url" placeholder="https://…" maxlength="2048"></div><div><label for="token">Token desta intake</label><input id="token" type="password" autocomplete="off" required></div></div>
<label for="note">Nota de proveniência (opcional)</label><textarea id="note" maxlength="2000" placeholder="Release, origem e contexto. Não inclua segredos."></textarea>
<button id="upload" disabled>Enviar e gerar objeto candidato</button><progress id="progress" value="0" max="100" hidden></progress><div id="result" role="status" aria-live="polite"></div></div>
<div class="panel"><h2>O que acontece depois</h2><p>O servidor grava em <code>.intake/files/</code> e emite um JSON em <code>.intake/objects/</code>. Se já existir um SHA256 pinado, divergência reprova e apaga o upload. Sem hash prévio, o SHA256 calculado só comprova integridade — <strong>não autenticidade nem compatibilidade</strong>.</p><p class="muted">Para ROMs multi-GB, uma eventual limitação do proxy de preview não é falha da ROM. Nesse caso, anexe o arquivo diretamente ou forneça armazenamento externo verificável. Esta página não é um mirror de produção: o Actions precisa de uma URL HTTPS acessível do mesmo arquivo, sempre sujeita ao SHA256 canônico. Git LFS/DVC não são habilitados por esta página.</p></div>
</main><script>
const $=id=>document.getElementById(id);let catalog=[];let lastObject=null;
function details(){const a=catalog.find(x=>x.intake_id===$('asset').value);if(!a)return;$('details').textContent=[`ID: ${a.asset_id}`,`Pin: ${a.pin||'não definido'}`,`Arquivo esperado: ${a.expected_filename||'não fixado'}`,`SHA256 esperado: ${a.expected_sha256||'não fornecido — candidato PENDING_REVIEW'}`,a.reason].join('\n');$('details').style.whiteSpace='pre-wrap';validate()}
function validate(){$('upload').disabled=!($('asset').value&&$('file').files[0]&&$('token').value.length>=16)}
async function load(){const r=await fetch('/api/catalog');if(!r.ok)throw new Error('Falha ao carregar catálogo');catalog=await r.json();for(const a of catalog){const o=document.createElement('option');o.value=a.intake_id;o.textContent=`${a.group} · ${a.asset_id}${a.upload_allowed?'':' · NÃO ENVIAR'}`;o.disabled=!a.upload_allowed;$('asset').appendChild(o)}const first=catalog.find(a=>a.upload_allowed);if(first){$('asset').value=first.intake_id;details()}}
function show(text){$('result').textContent=text}
function downloadObject(){if(!lastObject)return;const blob=new Blob([JSON.stringify(lastObject,null,2)+'\n'],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`${lastObject.asset.intake_id.replaceAll(':','-')}-${lastObject.file.sha256.slice(0,12)}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
$('asset').addEventListener('change',details);$('file').addEventListener('change',validate);$('token').addEventListener('input',validate);
$('upload').addEventListener('click',()=>{const file=$('file').files[0];if(!file)return;const q=new URLSearchParams({asset:$('asset').value,filename:file.name,source_url:$('source').value,note:$('note').value});const x=new XMLHttpRequest();x.open('POST','/api/upload?'+q);x.setRequestHeader('X-Intake-Token',$('token').value);x.setRequestHeader('Content-Type','application/octet-stream');$('upload').disabled=true;$('progress').hidden=false;$('progress').value=0;show('Enviando… o SHA256 será calculado no servidor.');x.upload.onprogress=e=>{if(e.lengthComputable)$('progress').value=Math.round(e.loaded/e.total*100)};x.onload=()=>{let data;try{data=JSON.parse(x.responseText)}catch{data={error:x.responseText||`HTTP ${x.status}`}}if(x.status>=200&&x.status<300){lastObject=data.object;show('Objeto candidato criado (não canônico):\n'+JSON.stringify(data.object,null,2));const b=document.createElement('button');b.textContent='Baixar objeto JSON';b.onclick=downloadObject;$('result').appendChild(document.createElement('br')); $('result').appendChild(b)}else{show(`Envio rejeitado (HTTP ${x.status}):\n${data.error||'erro desconhecido'}`)}$('progress').hidden=true;validate()};x.onerror=()=>{show('Falha de rede/proxy. Para arquivos multi-GB, use anexo direto ou armazenamento externo verificável.');$('progress').hidden=true;validate()};x.send(file)});
load().catch(e=>show(e.message));
</script></body></html>"""


class IntakeHandler(BaseHTTPRequestHandler):
    server_version = "PongIntake/1"

    @property
    def root(self) -> Path:
        return self.server.root  # type: ignore[attr-defined]

    @property
    def catalog(self) -> list[dict]:
        return self.server.catalog  # type: ignore[attr-defined]

    def send_data(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, status: int, value) -> None:
        self.send_data(status, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode(), "application/json; charset=utf-8")

    def log_message(self, fmt: str, *args) -> None:
        # Do not log query strings: optional provenance URLs can contain sensitive data.
        print(f"intake {self.command} {urlsplit(self.path).path} - {args[1] if len(args) > 1 else ''}", flush=True)

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/":
            self.send_data(200, HTML.encode(), "text/html; charset=utf-8")
        elif path == "/api/catalog":
            self.send_json(200, self.catalog)
        elif path == "/health":
            self.send_json(200, {"status": "ok", "canonical_objects_modified": False})
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        part_path: Path | None = None
        try:
            if not hmac.compare_digest(self.headers.get("X-Intake-Token", ""), self.server.token):  # type: ignore[attr-defined]
                raise UploadError(403, "invalid intake token")
            split = urlsplit(self.path)
            if split.path != "/api/upload":
                raise UploadError(404, "not found")
            if len(split.query) > MAX_METADATA:
                raise UploadError(413, "metadata is too large")
            query = parse_qs(split.query, keep_blank_values=True, max_num_fields=8)
            scalar = {key: values[-1] for key, values in query.items() if values}
            asset = next((item for item in self.catalog if item["intake_id"] == scalar.get("asset")), None)
            if not asset:
                raise UploadError(400, "unknown component; select an item from the fixed catalog")
            if not asset["upload_allowed"]:
                raise UploadError(403, "this component does not accept upload; supply redacted evidence through the approved private process")
            filename = safe_filename(scalar.get("filename", ""))
            source_url = scalar.get("source_url", "")
            note = scalar.get("note", "")
            if len(source_url) > 2048 or len(note) > 2000:
                raise UploadError(413, "metadata is too large")
            if source_url:
                parsed = urlsplit(source_url)
                if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                    raise UploadError(400, "source_url must be an HTTPS URL without embedded credentials")
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                length = 0
            if length <= 0:
                raise UploadError(411, "a non-empty file with Content-Length is required")
            if length > self.server.max_bytes:  # type: ignore[attr-defined]
                raise UploadError(413, f"file exceeds the {self.server.max_bytes} byte intake limit")  # type: ignore[attr-defined]
            intake = self.root / ".intake"
            tmp_dir = intake / "tmp"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(tmp_dir).free < length + 1024 ** 3:
                raise UploadError(507, "insufficient disk space while preserving the 1 GiB safety reserve")

            digest = hashlib.sha256()
            remaining = length
            with tempfile.NamedTemporaryFile(prefix="upload-", suffix=".part", dir=tmp_dir, delete=False) as handle:
                part_path = Path(handle.name)
                while remaining:
                    block = self.rfile.read(min(1024 * 1024, remaining))
                    if not block:
                        raise UploadError(400, "upload ended before Content-Length")
                    handle.write(block)
                    digest.update(block)
                    remaining -= len(block)
                handle.flush()
                os.fsync(handle.fileno())
            actual = digest.hexdigest()
            expected = asset.get("expected_sha256")
            if expected and not hmac.compare_digest(actual, expected):
                part_path.unlink(missing_ok=True)
                part_path = None
                raise UploadError(422, f"SHA256 mismatch: expected {expected}, got {actual}; upload deleted")

            destination_dir = intake / "files" / asset["intake_id"].replace(":", "/") / actual
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination = destination_dir / filename
            duplicate = destination.exists()
            if duplicate:
                if destination.stat().st_size != length:
                    raise UploadError(409, "content-addressed destination collision")
                part_path.unlink()
            else:
                os.replace(part_path, destination)
            part_path = None
            object_path = intake / "objects" / asset["intake_id"].replace(":", "/") / f"{actual}.json"
            object_path.parent.mkdir(parents=True, exist_ok=True)
            candidate = {
                "schema": SCHEMA,
                "status": "HASH_MATCH_PENDING_REVIEW" if expected else "PENDING_REVIEW",
                "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "asset": {key: asset[key] for key in ("intake_id", "asset_id", "kind", "required", "pin", "source")},
                "file": {
                    "filename": filename, "bytes": length, "sha256": actual,
                    "path": str(destination.relative_to(self.root)),
                    "expected_sha256": expected, "hash_match": bool(expected) if expected else None,
                },
                "provenance": {"source_url": source_url or None, "note": note or None, "sha256_origin": "computed_from_upload"},
                "gates": {
                    "canonical_object_modified": False, "authenticity_verified": False,
                    "compatibility_verified": False, "ci_triggered": False,
                    "staging_authorized": False, "release_authorized": False, "flash_authorized": False,
                },
                "duplicate_content": duplicate,
            }
            if object_path.exists():
                previous = json.loads(object_path.read_text())
                if previous.get("file", {}).get("sha256") != actual:
                    raise UploadError(409, "candidate object collision")
                candidate = previous
                candidate["duplicate_content"] = True
            else:
                temporary = object_path.with_suffix(".tmp")
                temporary.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n")
                os.replace(temporary, object_path)
            candidate["object_path"] = str(object_path.relative_to(self.root))
            self.send_json(200 if duplicate else 201, {"object": candidate})
        except UploadError as error:
            if part_path:
                part_path.unlink(missing_ok=True)
            self.send_json(error.status, {"error": str(error)})
        except (ValueError, json.JSONDecodeError) as error:
            if part_path:
                part_path.unlink(missing_ok=True)
            self.send_json(400, {"error": str(error)})
        except (BrokenPipeError, ConnectionResetError):
            if part_path:
                part_path.unlink(missing_ok=True)
        except Exception as error:
            if part_path:
                part_path.unlink(missing_ok=True)
            print(f"intake internal error: {type(error).__name__}", flush=True)
            try:
                self.send_json(500, {"error": "internal intake error; no canonical object was changed"})
            except (BrokenPipeError, ConnectionResetError):
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--max-gib", type=float, default=4.0)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    server = HTTPServer((args.host, args.port), IntakeHandler)
    server.root = root  # type: ignore[attr-defined]
    server.catalog = load_catalog(root)  # type: ignore[attr-defined]
    server.token = intake_token(root)  # type: ignore[attr-defined]
    server.max_bytes = int(args.max_gib * 1024 ** 3)  # type: ignore[attr-defined]
    print(f"Pong intake listening on {args.host}:{args.port}; {len(server.catalog)} catalog entries; token in .intake/token", flush=True)  # type: ignore[attr-defined]
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
