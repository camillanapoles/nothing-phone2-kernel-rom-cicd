#!/usr/bin/env python3
"""Temporary chunked artifact intake for the Pong CI/CD collection.

Streams small browser chunks to .intake/, verifies each chunk and the complete
SHA256, and writes a non-canonical candidate object. It never edits objects/,
runs CI, or authorizes staging/release. No third-party packages are required.
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
MAX_METADATA = 16384
MIRROR_TTL_SECONDS = 24 * 60 * 60


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


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", prefix=path.name + "-", suffix=".tmp", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


class UploadError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def metadata_from_values(catalog: list[dict], values: dict) -> tuple[dict, str, str, str]:
    asset = next((item for item in catalog if item["intake_id"] == values.get("asset")), None)
    if not asset:
        raise UploadError(400, "unknown component; select an item from the fixed catalog")
    if not asset["upload_allowed"]:
        raise UploadError(403, "this component does not accept upload; supply redacted evidence through the approved private process")
    try:
        filename = safe_filename(str(values.get("filename", "")))
    except ValueError as error:
        raise UploadError(400, str(error)) from error
    source_url = str(values.get("source_url") or "")
    note = str(values.get("note") or "")
    if len(source_url) > 2048 or len(note) > 2000:
        raise UploadError(413, "metadata is too large")
    if source_url:
        parsed = urlsplit(source_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise UploadError(400, "source_url must be an HTTPS URL without embedded credentials")
    return asset, filename, source_url, note


def store_candidate(
    root: Path, asset: dict, filename: str, source_url: str, note: str,
    part_path: Path, length: int, actual: str, transport: dict,
) -> tuple[dict, bool, Path]:
    expected = asset.get("expected_sha256")
    if expected and not hmac.compare_digest(actual, expected):
        part_path.unlink(missing_ok=True)
        raise UploadError(422, f"SHA256 mismatch: expected {expected}, got {actual}; upload deleted")

    intake = root / ".intake"
    destination_dir = intake / "files" / asset["intake_id"].replace(":", "/") / actual
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / filename
    duplicate = destination.exists()
    if duplicate:
        if destination.stat().st_size != length:
            raise UploadError(409, "content-addressed destination collision")
        part_path.unlink(missing_ok=True)
    else:
        os.replace(part_path, destination)

    object_path = intake / "objects" / asset["intake_id"].replace(":", "/") / f"{actual}.json"
    candidate = {
        "schema": SCHEMA,
        "status": "HASH_MATCH_PENDING_REVIEW" if expected else "PENDING_REVIEW",
        "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "asset": {key: asset[key] for key in ("intake_id", "asset_id", "kind", "required", "pin", "source")},
        "file": {
            "filename": filename, "bytes": length, "sha256": actual,
            "path": str(destination.relative_to(root)),
            "expected_sha256": expected, "hash_match": bool(expected) if expected else None,
        },
        "provenance": {"source_url": source_url or None, "note": note or None, "sha256_origin": "computed_from_upload"},
        "transport": transport,
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
        atomic_json(object_path, candidate)
    candidate["object_path"] = str(object_path.relative_to(root))
    return candidate, duplicate, destination


def create_mirror(root: Path, upload_id: str, asset: dict, candidate: dict, destination: Path) -> dict | None:
    actual = candidate["file"]["sha256"]
    if asset["intake_id"] != "rom:vanilla" or not asset.get("expected_sha256"):
        return None
    if not hmac.compare_digest(actual, asset["expected_sha256"]):
        return None
    key = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + MIRROR_TTL_SECONDS
    record = {
        "schema": "pong-intake-mirror/1", "path": str(destination.relative_to(root)),
        "filename": candidate["file"]["filename"], "bytes": candidate["file"]["bytes"],
        "sha256": actual, "key_sha256": hashlib.sha256(key.encode()).hexdigest(),
        "expires_at": expires_at,
    }
    atomic_json(root / ".intake/mirrors" / f"{upload_id}.json", record)
    return {
        "mirror_path": f"/mirror/{upload_id}?key={key}",
        "mirror_expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expires_at)),
    }


HTML = r"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pong · intake de artefatos</title><style>
:root{color-scheme:dark;--bg:#0b1017;--panel:#131c27;--line:#2c3a49;--text:#e8eef5;--muted:#a7b5c4;--accent:#64d2ff;--warn:#ffcf66}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,sans-serif}main{max-width:880px;margin:auto;padding:32px 18px 60px}h1{font-size:1.8rem;margin-bottom:.3rem}h2{font-size:1.1rem;margin-top:2rem}.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;margin-top:18px}.warning{border-color:#80652d;color:var(--warn)}label{display:block;font-weight:650;margin:14px 0 6px}input,select,textarea,button{width:100%;font:inherit;border-radius:8px;border:1px solid var(--line);padding:11px;background:#0d1520;color:var(--text)}textarea{min-height:76px;resize:vertical}button{margin-top:18px;background:#14536b;border-color:#267a9b;font-weight:700;cursor:pointer}button:disabled{opacity:.55;cursor:wait}.muted,small{color:var(--muted)}code,pre{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#0b121b;border:1px solid var(--line);padding:12px;border-radius:8px;max-height:360px;overflow:auto}progress{width:100%;height:20px;margin-top:14px}#result{overflow-wrap:anywhere;white-space:pre-wrap}a{color:var(--accent)}.row{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:650px){.row{grid-template-columns:1fr}}
</style></head><body><main>
<h1>Pong · intake temporária</h1><p class="muted">Arquivo → partes verificadas → SHA256 completo → objeto candidato. Nenhum binário entra no Git.</p>
<div class="panel warning"><strong>Não envie <code>keybox.xml</code>, chaves, tokens, credenciais ou dados pessoais.</strong><br>Upload não altera <code>objects/</code>, não dispara CI e não autoriza teste, flash, staging ou release. Todo item permanece em revisão.</div>
<div class="panel"><label for="asset">Componente orientado pelos contratos atuais</label><select id="asset"></select><div id="details" class="muted" style="margin-top:12px"></div>
<label for="file">Arquivo</label><input id="file" type="file">
<div class="row"><div><label for="source">URL de origem oficial (opcional)</label><input id="source" type="url" placeholder="https://…" maxlength="2048"></div><div><label for="token">Token desta intake</label><input id="token" type="password" autocomplete="off" required></div></div>
<label for="note">Nota de proveniência (opcional)</label><textarea id="note" maxlength="2000" placeholder="Release, origem e contexto. Não inclua segredos."></textarea>
<button id="upload" disabled>Enviar em partes e gerar objeto</button><progress id="progress" value="0" max="100" hidden></progress><div id="result" role="status" aria-live="polite"></div></div>
<div class="panel"><h2>Como o 413 é evitado</h2><p>O navegador envia partes pequenas, com SHA256 por parte e retentativa. O servidor grava em <code>.intake/files/</code>, confere o hash do arquivo inteiro e emite um JSON em <code>.intake/objects/</code>. Divergência de um hash pinado reprova e apaga o upload.</p><p>Para a <strong>ROM Vanilla exata</strong>, um hash completo correspondente libera um link temporário de 24 horas. Use a URL completa gerada como <code>rom_mirror_url</code> no dispatch ou como variável <code>PONG_ROM_MIRROR_URL</code>. O Actions ainda verificará o SHA256 canônico.</p><p class="muted">Sem hash prévio, o SHA256 calculado só comprova integridade — não autenticidade nem compatibilidade. O link temporário não é release nem armazenamento DVC/LFS.</p></div>
</main><script>
const $=id=>document.getElementById(id);let catalog=[];let lastObject=null;let busy=false;
function details(){const a=catalog.find(x=>x.intake_id===$('asset').value);if(!a)return;$('details').textContent=[`ID: ${a.asset_id}`,`Pin: ${a.pin||'não definido'}`,`Arquivo esperado: ${a.expected_filename||'não fixado'}`,`SHA256 esperado: ${a.expected_sha256||'não fornecido — candidato PENDING_REVIEW'}`,a.reason].join('\n');$('details').style.whiteSpace='pre-wrap';validate()}
function validate(){$('upload').disabled=busy||!($('asset').value&&$('file').files[0]&&$('token').value.length>=16)}
async function load(){const r=await fetch('/api/catalog');if(!r.ok)throw new Error('Falha ao carregar catálogo');catalog=await r.json();for(const a of catalog){const o=document.createElement('option');o.value=a.intake_id;o.textContent=`${a.group} · ${a.asset_id}${a.upload_allowed?'':' · NÃO ENVIAR'}`;o.disabled=!a.upload_allowed;$('asset').appendChild(o)}const first=catalog.find(a=>a.upload_allowed);if(first){$('asset').value=first.intake_id;details()}}
function show(text){$('result').textContent=text}
function errorFrom(status,text){try{const x=JSON.parse(text);return new Error(x.error||`HTTP ${status}`)}catch{return new Error(`HTTP ${status}: resposta não JSON do proxy ou servidor`)}}
async function api(url,options){const r=await fetch(url,options);const text=await r.text();if(!r.ok){const e=errorFrom(r.status,text);e.status=r.status;throw e}return JSON.parse(text)}
function downloadObject(){if(!lastObject)return;const blob=new Blob([JSON.stringify(lastObject,null,2)+'\n'],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`${lastObject.asset.intake_id.replaceAll(':','-')}-${lastObject.file.sha256.slice(0,12)}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
function success(data){lastObject=data.object;show('Objeto candidato criado (não canônico):\n'+JSON.stringify(data.object,null,2));const b=document.createElement('button');b.textContent='Baixar objeto JSON';b.onclick=downloadObject;$('result').appendChild(document.createElement('br')); $('result').appendChild(b);if(data.mirror_path){const url=location.origin+data.mirror_path;const label=document.createElement('label');label.textContent='ROM_MIRROR_URL temporária (expira '+data.mirror_expires_at+')';const input=document.createElement('input');input.readOnly=true;input.value=url;const copy=document.createElement('button');copy.textContent='Copiar URL do mirror';copy.onclick=async()=>{input.select();try{await navigator.clipboard.writeText(url)}catch{document.execCommand('copy')}};$('result').appendChild(label);$('result').appendChild(input);$('result').appendChild(copy);const note=document.createElement('p');note.textContent='Envie esta URL completa para continuar o CI. Ela não altera o SHA256 exigido nem autoriza release.';$('result').appendChild(note)}}
function chunkRequest(id,index,blob,hash,offset,total){return new Promise((resolve,reject)=>{const x=new XMLHttpRequest();x.open('POST',`/api/upload/chunk?id=${id}&index=${index}`);x.setRequestHeader('X-Intake-Token',$('token').value);x.setRequestHeader('X-Chunk-SHA256',hash);x.setRequestHeader('Content-Type','application/octet-stream');x.upload.onprogress=e=>{if(e.lengthComputable){$('progress').value=(offset+e.loaded)/total*100;show(`Enviando… ${Math.floor((offset+e.loaded)/total*100)}% · parte ${index+1}`)}};x.onload=()=>{if(x.status>=200&&x.status<300){try{resolve(JSON.parse(x.responseText))}catch{reject(new Error('Resposta JSON inválida do servidor'))}}else{const e=errorFrom(x.status,x.responseText);e.status=x.status;reject(e)}};x.onerror=()=>reject(new Error('falha de rede no envio da parte'));x.send(blob)})}
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function retry(operation){let last;for(let attempt=1;attempt<=5;attempt++){try{return await operation()}catch(e){last=e;if(attempt===5||(e.status>=400&&e.status<500&&e.status!==408&&e.status!==429))throw e;await pause(attempt*1000)}}throw last}
$('asset').addEventListener('change',details);$('file').addEventListener('change',validate);$('token').addEventListener('input',validate);
$('upload').addEventListener('click',async()=>{const file=$('file').files[0];if(!file||busy)return;if(!crypto.subtle){show('Este navegador não oferece WebCrypto SHA256 em contexto seguro.');return}busy=true;validate();$('progress').hidden=false;$('progress').value=0;try{show('Inicializando upload em partes…');const init=await api('/api/upload/init',{method:'POST',headers:{'X-Intake-Token':$('token').value,'Content-Type':'application/json'},body:JSON.stringify({asset:$('asset').value,filename:file.name,size:file.size,source_url:$('source').value,note:$('note').value})});const total=Math.ceil(file.size/init.chunk_size);for(let index=0;index<total;index++){const offset=index*init.chunk_size;const blob=file.slice(offset,Math.min(offset+init.chunk_size,file.size));const buffer=await blob.arrayBuffer();const digest=await crypto.subtle.digest('SHA-256',buffer);const hash=Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('');await retry(()=>chunkRequest(init.upload_id,index,blob,hash,offset,file.size))}show('Partes recebidas. Verificando o SHA256 completo…');const data=await retry(()=>api(`/api/upload/complete?id=${init.upload_id}`,{method:'POST',headers:{'X-Intake-Token':$('token').value}}));$('progress').value=100;success(data)}catch(e){show(`Envio rejeitado: ${e.message}\nNenhum objeto canônico foi alterado.`)}finally{busy=false;$('progress').hidden=true;validate()}});
load().catch(e=>show(e.message));
</script></body></html>"""


class IntakeHandler(BaseHTTPRequestHandler):
    server_version = "PongIntake/2"

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
        print(f"intake {self.command} {urlsplit(self.path).path} - {args[1] if len(args) > 1 else ''}", flush=True)

    def authenticate(self) -> None:
        if not hmac.compare_digest(self.headers.get("X-Intake-Token", ""), self.server.token):  # type: ignore[attr-defined]
            raise UploadError(403, "invalid intake token")

    def read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_METADATA:
            raise UploadError(411 if length <= 0 else 413, "a small JSON body with Content-Length is required")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise UploadError(400, "JSON body ended before Content-Length")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            raise UploadError(400, "invalid JSON body") from error
        if not isinstance(value, dict):
            raise UploadError(400, "JSON body must be an object")
        return value

    def session_dir(self, upload_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", upload_id):
            raise UploadError(400, "invalid upload id")
        return self.root / ".intake/sessions" / upload_id

    def load_session(self, upload_id: str) -> tuple[Path, dict]:
        directory = self.session_dir(upload_id)
        path = directory / "session.json"
        if not path.is_file():
            raise UploadError(404, "upload session not found or expired")
        return directory, json.loads(path.read_text())

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        try:
            split = urlsplit(self.path)
            path = split.path
            if path == "/":
                self.send_data(200, HTML.encode(), "text/html; charset=utf-8")
            elif path == "/api/catalog":
                self.send_json(200, self.catalog)
            elif path == "/health":
                self.send_json(200, {"status": "ok", "chunked_upload": True, "canonical_objects_modified": False})
            elif path == "/api/upload/status":
                self.authenticate()
                upload_id = parse_qs(split.query).get("id", [""])[-1]
                _, session = self.load_session(upload_id)
                directory = self.session_dir(upload_id)
                received = sorted(int(p.stem) for p in (directory / "chunks").glob("*.json")) if (directory / "chunks").exists() else []
                self.send_json(200, {"upload_id": upload_id, "status": session["status"], "bytes": session["bytes"], "chunk_size": session["chunk_size"], "received": received})
            elif re.fullmatch(r"/mirror/[0-9a-f]{32}", path):
                self.serve_mirror(split)
            else:
                self.send_json(404, {"error": "not found"})
        except UploadError as error:
            self.send_json(error.status, {"error": str(error)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:
            print(f"intake GET internal error: {type(error).__name__}", flush=True)
            try:
                self.send_json(500, {"error": "internal intake error"})
            except (BrokenPipeError, ConnectionResetError):
                pass

    def serve_mirror(self, split) -> None:
        upload_id = split.path.rsplit("/", 1)[-1]
        record_path = self.root / ".intake/mirrors" / f"{upload_id}.json"
        key = parse_qs(split.query).get("key", [""])[-1]
        if not record_path.is_file() or not key:
            raise UploadError(404, "mirror not found or expired")
        record = json.loads(record_path.read_text())
        if time.time() > record["expires_at"] or not hmac.compare_digest(hashlib.sha256(key.encode()).hexdigest(), record["key_sha256"]):
            raise UploadError(404, "mirror not found or expired")
        base = (self.root / ".intake/files").resolve()
        path = (self.root / record["path"]).resolve()
        if not path.is_relative_to(base) or not path.is_file() or path.stat().st_size != record["bytes"]:
            raise UploadError(404, "mirror content is unavailable")
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Length", str(record["bytes"]))
        self.send_header("Content-Disposition", f'attachment; filename="{record["filename"]}"')
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if self.command != "HEAD":
            with path.open("rb") as handle:
                while block := handle.read(1024 * 1024):
                    self.wfile.write(block)

    def do_POST(self) -> None:
        try:
            self.authenticate()
            path = urlsplit(self.path).path
            if path == "/api/upload/init":
                self.upload_init()
            elif path == "/api/upload/chunk":
                self.upload_chunk()
            elif path == "/api/upload/complete":
                self.upload_complete()
            else:
                raise UploadError(404, "not found; reload the chunked intake page")
        except UploadError as error:
            try:
                self.send_json(error.status, {"error": str(error)})
            except (BrokenPipeError, ConnectionResetError):
                pass
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:
            print(f"intake POST internal error: {type(error).__name__}", flush=True)
            try:
                self.send_json(500, {"error": "internal intake error; no canonical object was changed"})
            except (BrokenPipeError, ConnectionResetError):
                pass

    def upload_init(self) -> None:
        values = self.read_json()
        asset, filename, source_url, note = metadata_from_values(self.catalog, values)
        size = values.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise UploadError(400, "size must be a positive integer")
        if size > self.server.max_bytes:  # type: ignore[attr-defined]
            raise UploadError(413, f"file exceeds the {self.server.max_bytes} byte intake limit")  # type: ignore[attr-defined]
        intake = self.root / ".intake"
        if shutil.disk_usage(intake).free < size + 1024 ** 3:
            raise UploadError(507, "insufficient disk space while preserving the 1 GiB safety reserve")
        upload_id = secrets.token_hex(16)
        directory = self.session_dir(upload_id)
        (directory / "chunks").mkdir(parents=True, exist_ok=False)
        with (directory / "data.part").open("wb") as handle:
            handle.truncate(size)
        chunk_size = self.server.chunk_size  # type: ignore[attr-defined]
        session = {
            "schema": "pong-intake-session/1", "upload_id": upload_id,
            "asset": asset["intake_id"], "filename": filename,
            "source_url": source_url, "note": note, "bytes": size,
            "chunk_size": chunk_size, "chunks_total": (size + chunk_size - 1) // chunk_size,
            "status": "receiving", "created_at": int(time.time()),
        }
        atomic_json(directory / "session.json", session)
        self.send_json(201, {"upload_id": upload_id, "chunk_size": chunk_size, "chunks_total": session["chunks_total"]})

    def upload_chunk(self) -> None:
        split = urlsplit(self.path)
        query = parse_qs(split.query, keep_blank_values=True, max_num_fields=4)
        upload_id = query.get("id", [""])[-1]
        try:
            index = int(query.get("index", [""])[-1])
        except ValueError as error:
            raise UploadError(400, "invalid chunk index") from error
        directory, session = self.load_session(upload_id)
        if session["status"] != "receiving":
            raise UploadError(409, "upload session is not receiving chunks")
        if index < 0 or index >= session["chunks_total"]:
            raise UploadError(400, "chunk index is outside the session")
        offset = index * session["chunk_size"]
        expected_length = min(session["chunk_size"], session["bytes"] - offset)
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = 0
        if length != expected_length:
            raise UploadError(411, f"chunk {index} requires Content-Length {expected_length}")
        expected_hash = self.headers.get("X-Chunk-SHA256", "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise UploadError(400, "X-Chunk-SHA256 must be a complete SHA256")
        body = bytearray()
        while len(body) < length:
            block = self.rfile.read(min(1024 * 1024, length - len(body)))
            if not block:
                raise UploadError(400, "chunk ended before Content-Length")
            body.extend(block)
        actual_hash = hashlib.sha256(body).hexdigest()
        if not hmac.compare_digest(actual_hash, expected_hash):
            raise UploadError(422, f"chunk {index} SHA256 mismatch; upload the chunk again")
        fd = os.open(directory / "data.part", os.O_WRONLY)
        try:
            view = memoryview(body)
            written = 0
            while written < length:
                written += os.pwrite(fd, view[written:], offset + written)
            os.fdatasync(fd)
        finally:
            os.close(fd)
        atomic_json(directory / "chunks" / f"{index:08d}.json", {"sha256": actual_hash, "bytes": length})
        received = len(list((directory / "chunks").glob("*.json")))
        self.send_json(200, {"index": index, "received": received, "chunks_total": session["chunks_total"]})

    def upload_complete(self) -> None:
        split = urlsplit(self.path)
        upload_id = parse_qs(split.query, keep_blank_values=True, max_num_fields=2).get("id", [""])[-1]
        directory, session = self.load_session(upload_id)
        result_path = directory / "result.json"
        if result_path.is_file():
            self.send_json(200, json.loads(result_path.read_text()))
            return
        if session["status"] != "receiving":
            raise UploadError(409, "upload session is not completable")
        missing = []
        for index in range(session["chunks_total"]):
            marker = directory / "chunks" / f"{index:08d}.json"
            if not marker.is_file():
                missing.append(index)
                continue
            value = json.loads(marker.read_text())
            expected_length = min(session["chunk_size"], session["bytes"] - index * session["chunk_size"])
            if value.get("bytes") != expected_length or not re.fullmatch(r"[0-9a-f]{64}", value.get("sha256", "")):
                raise UploadError(409, f"chunk marker {index} is invalid; upload it again")
        if missing:
            raise UploadError(409, f"upload is incomplete; missing chunks: {missing[:20]}")
        part_path = directory / "data.part"
        if not part_path.is_file() or part_path.stat().st_size != session["bytes"]:
            raise UploadError(409, "assembled upload has the wrong size")
        asset = next(item for item in self.catalog if item["intake_id"] == session["asset"])
        actual = file_sha256(part_path)
        try:
            candidate, duplicate, destination = store_candidate(
                self.root, asset, session["filename"], session["source_url"], session["note"],
                part_path, session["bytes"], actual,
                {"mode": "chunked", "chunk_size": session["chunk_size"], "chunks": session["chunks_total"]},
            )
        except UploadError:
            session["status"] = "rejected"
            atomic_json(directory / "session.json", session)
            raise
        response = {"object": candidate}
        mirror = create_mirror(self.root, upload_id, asset, candidate, destination)
        if mirror:
            response.update(mirror)
        atomic_json(result_path, response)
        session["status"] = "complete"
        atomic_json(directory / "session.json", session)
        for marker in (directory / "chunks").glob("*.json"):
            marker.unlink()
        (directory / "chunks").rmdir()
        self.send_json(200 if duplicate else 201, response)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--max-gib", type=float, default=4.0)
    parser.add_argument("--chunk-size", type=int, default=8 * 1024 * 1024)
    args = parser.parse_args()
    if args.chunk_size < 1024 * 1024 or args.chunk_size > 16 * 1024 * 1024:
        parser.error("--chunk-size must be between 1 MiB and 16 MiB")
    root = Path(__file__).resolve().parents[1]
    server = HTTPServer((args.host, args.port), IntakeHandler)
    server.root = root  # type: ignore[attr-defined]
    server.catalog = load_catalog(root)  # type: ignore[attr-defined]
    server.token = intake_token(root)  # type: ignore[attr-defined]
    server.max_bytes = int(args.max_gib * 1024 ** 3)  # type: ignore[attr-defined]
    server.chunk_size = args.chunk_size  # type: ignore[attr-defined]
    print(f"Pong intake listening on {args.host}:{args.port}; {len(server.catalog)} catalog entries; chunks {args.chunk_size} bytes; token in .intake/token", flush=True)  # type: ignore[attr-defined]
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
