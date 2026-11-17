"""Audita uma lista explícita e empacota somente a distribuição revisada, sem rede."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_ROOTS = {'base','perfil','config','data','entrada','output','candidaturas','relatorios','tmp','.git','.codex','.agents','.aws'}


def files(root=ROOT):
    root = Path(root).resolve()
    manifest = json.loads((root/'PUBLICACAO.json').read_text(encoding='utf-8'))
    names = manifest['arquivos']
    if not isinstance(names,list) or len(set(names)) != len(names):
        raise ValueError('Manifesto de publicação inválido')
    for name in names:
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] in PRIVATE_ROOTS or '\\' in name:
            raise ValueError('Caminho não publicável no manifesto')
        resolved = (root/path).resolve()
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise ValueError('Arquivo ausente ou fora do projeto: '+name)
        if any((root/Path(*path.parts[:i])).is_symlink() for i in range(1,len(path.parts)+1)):
            raise ValueError('Links simbólicos não são publicáveis')
    return names


def audit(root=ROOT, inspect_git=True):
    root = Path(root).resolve()
    names = files(root)
    problems = []
    personal = []
    profile = root/'perfil/fatos_confirmados.json'
    if profile.exists():
        data = json.loads(profile.read_text(encoding='utf-8-sig'))
        personal = [data.get(k) for k in ('nome','telefone','email')]
        personal += list(data.get('links',{}).values())
        personal = [v for v in personal if isinstance(v,str) and len(v)>5]
    patterns = {
        'caminho_de_usuario': re.compile(r'(?:[A-Z]:[\\/]+Users[\\/]+[^\s\\/]+|'+'/'+'home'+'/'+r'[^\s/]+)',re.I),
        'email_nao_ficticio': re.compile(r'[A-Z0-9._%+-]+@(?!example\.(?:com|org|net)\b)[A-Z0-9.-]+\.[A-Z]{2,}',re.I),
        'id_google_real': re.compile(r'(?:spreadsheets/d/|drive\.google\.com/file/d/)[A-Za-z0-9_-]{20,}'),
        'identificador_de_conexao': re.compile(r'\blink_[a-f0-9]{20,}\b|\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b',re.I),
        'chave_privada': re.compile(r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|\bgh[pousr]_[A-Za-z0-9]{20,}|\bsk-[A-Za-z0-9_-]{20,}'),
    }
    for name in names:
        content = (root/name).read_text(encoding='utf-8-sig')
        for label, pattern in patterns.items():
            if pattern.search(content):
                problems.append({'arquivo':name,'motivo':label})
        if any(value.casefold() in content.casefold() for value in personal):
            problems.append({'arquivo':name,'motivo':'dado_do_perfil_local'})
    if inspect_git and (root/'.git').exists():
        process = subprocess.run(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=root,
                                 capture_output=True,check=True)
        candidates = {v for v in process.stdout.decode('utf-8').split('\0') if v}
        problems += [{'arquivo':name,'motivo':'arquivo_git_fora_do_manifesto'} for name in sorted(candidates-set(names))]
        for name in names:
            ignored = subprocess.run(['git','check-ignore','-q','--',name],cwd=root,capture_output=True)
            if ignored.returncode == 0:
                problems.append({'arquivo':name,'motivo':'arquivo_publico_ignorado'})
    return {'ok':not problems,'arquivos':len(names),'problemas':problems}


def package(destination, root=ROOT):
    root = Path(root).resolve()
    result = audit(root)
    if not result['ok']:
        raise ValueError('Publicação bloqueada; execute auditoria e revise os arquivos sinalizados')
    names = files(root)
    destination = Path(destination).resolve()
    if destination.exists() or destination == root or destination.is_relative_to(root/'src'):
        raise ValueError('Destino deve ser um ZIP novo, fora das fontes')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.writestr(name,(root/name).read_bytes())
    return {**result,'pacote':str(destination),'sha256':hashlib.sha256(destination.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pacote',help='Cria ZIP novo somente após auditoria')
    args = parser.parse_args()
    result = package(args.pacote) if args.pacote else audit()
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result['ok']: raise SystemExit(2)


if __name__ == '__main__':
    main()
