"""Layout do currículo: seções e tópicos, mantendo os trechos aprovados."""
from xml.sax.saxutils import escape
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4

def render_resume(pdf, facts, claims, title):
    styles = {
        'name': ParagraphStyle('name',fontName='Helvetica-Bold',fontSize=18,leading=22,spaceAfter=3),
        'subtitle': ParagraphStyle('subtitle',fontName='Helvetica-Bold',fontSize=9.7,leading=13,spaceAfter=4),
        'body': ParagraphStyle('body',fontName='Helvetica',fontSize=9.3,leading=12,spaceAfter=3),
        'heading': ParagraphStyle('heading',fontName='Helvetica-Bold',fontSize=11,leading=14,spaceBefore=7,spaceAfter=4,keepWithNext=True),
        'label': ParagraphStyle('label',fontName='Helvetica-Bold',fontSize=9.5,leading=12,spaceBefore=2,spaceAfter=3,keepWithNext=True),
        'bullet': ParagraphStyle('bullet',fontName='Helvetica',fontSize=9.3,leading=12,leftIndent=10,firstLineIndent=-8,spaceAfter=2),
    }
    story=[]
    fragments=[]
    def add(text,kind='body',bullet=False):
        fragments.append(text)
        story.append(Paragraph(('&#8226; ' if bullet else '')+escape(text),styles[kind]))
    add(facts['nome'],'name')
    subtitle=facts.get('subtitulo_curriculo') or 'Objetivo: '+title
    add(subtitle,'subtitle')
    add(f"{facts['cidade']} | {facts['telefone']} | {facts['email']}")
    story.append(Paragraph(' | '.join(f'<link href="{escape(url)}" color="#21678b">{escape(name)}</link>' for name,url in facts['links'].items()),styles['body']))
    labels={'resumo':'Resumo profissional','estagio':'Experiência profissional',
            'experiencia':'Experiência profissional','competencias':'Competências',
            'formacao':'Formação','ingles':'Idiomas'}
    for claim in claims:
        metadata=facts['afirmacoes'][claim['id']]
        add(metadata.get('secao') or labels.get(claim['id'],'Informações confirmadas'),'heading')
        # O texto aprovado é preservado; IDs de projetos não dependem de uma pessoa.
        add(claim['texto'])
    SimpleDocTemplate(str(pdf),pagesize=A4,leftMargin=52,rightMargin=52,topMargin=43,bottomMargin=39,
        title='Currículo - '+facts['nome'],author=facts['nome']).build(story)
    return fragments
