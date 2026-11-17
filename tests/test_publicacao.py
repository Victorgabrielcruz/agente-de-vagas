import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.publicacao import audit, files, package


class PublicacaoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'PUBLICACAO.json').write_text(json.dumps({'arquivos':['PUBLICACAO.json','README.md']}),encoding='utf-8')
        (self.root/'README.md').write_text('Distribuição fictícia, sem dados de uma instalação.',encoding='utf-8')

    def test_package_contains_only_explicit_allowlist(self):
        (self.root/'data').mkdir()
        (self.root/'data/privado.json').write_text('não publicar',encoding='utf-8')
        result=package(self.root/'pacote.zip',root=self.root)
        self.assertTrue(result['ok'])
        with zipfile.ZipFile(self.root/'pacote.zip') as archive:
            self.assertEqual(set(archive.namelist()),{'PUBLICACAO.json','README.md'})

    def test_personal_contacts_and_google_identifiers_are_blocked(self):
        (self.root/'perfil').mkdir()
        (self.root/'perfil/fatos_confirmados.json').write_text(json.dumps({'nome':'Pessoa Fictícia Exclusiva','email':'pessoa@example.org','links':{}}),encoding='utf-8')
        (self.root/'README.md').write_text('Pessoa Fictícia Exclusiva',encoding='utf-8')
        self.assertFalse(audit(self.root,inspect_git=False)['ok'])
        (self.root/'README.md').write_text('https://'+'docs.google.com/spreadsheets/d/'+'A'*30,encoding='utf-8')
        self.assertFalse(audit(self.root,inspect_git=False)['ok'])
        with self.assertRaises(ValueError): package(self.root/'bloqueado.zip',root=self.root)
        self.assertFalse((self.root/'bloqueado.zip').exists())

    def test_private_paths_and_traversal_cannot_be_allowlisted(self):
        for name in ('data/privado.json','../fora.txt','config/preferencias.yaml'):
            with self.subTest(name=name):
                (self.root/'PUBLICACAO.json').write_text(json.dumps({'arquivos':[name]}),encoding='utf-8')
                with self.assertRaises(ValueError): files(self.root)
