from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pypdfium2 as pdfium
from src.core import ROOT, write, now
for path in (ROOT/'candidaturas').rglob('curriculo.pdf'):
    doc=pdfium.PdfDocument(path)
    for i in range(len(doc)):
        image=doc[i].render(scale=1.5).to_pil()
        image.save(path.with_name(f'pagina-{i+1}.png'))
    print(str(path),len(doc),'páginas renderizadas')
