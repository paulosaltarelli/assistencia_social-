import uuid
from django.apps import apps
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.models.functions import Coalesce
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render as django_render
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters
from atendimentos.acesso import municipal, registrar_evento, tem_permissao
from atendimentos.models import Atendimento, Cidadao, Familia
from .forms import AtendimentoForm, BuscaDocumento, FamiliaForm, PessoaForm
from .identificacao import indice
from .models import AcompanhamentoAtendimento, AtualizacaoCadastro, ComplementoFamilia, ComplementoPessoa, NotaTecnica


def render(request, template, contexto):
    contexto.update(pode_cadastros=tem_permissao(request.vinculo, 'cadastros.editar'), pode_atendimentos=tem_permissao(request.vinculo, 'atendimentos.editar'))
    return django_render(request, template, contexto)


def uuid_seguro(valor):
    try:
        return uuid.UUID(str(valor))
    except (ValueError, TypeError, AttributeError):
        return None


def contexto_selecao(request, tipo, familia=None):
    q = request.GET.get('selecionar', '').strip()[:100]
    if tipo == 'familia':
        consulta = Familia.objects.filter(municipio=request.municipio).order_by('referencia', 'id')
        if q:
            consulta = consulta.filter(referencia__icontains=q)
    else:
        consulta = Cidadao.objects.filter(municipio=request.municipio).select_related('familia', 'complemento').order_by('nome', 'id')
        if familia:
            consulta = consulta.filter(familia=familia)
        if q:
            consulta = consulta.filter(Q(nome__icontains=q) | Q(familia__referencia__icontains=q))
    return {'opcoes': paginar(request, consulta, 'selecao_page'), 'selecionar': q, 'parametro': {'familia': 'familia', 'cidadao': 'cidadao', 'responsavel': 'responsavel'}[tipo]}


def paginar(request, consulta, chave='page'):
    return Paginator(consulta, 25).get_page(request.GET.get(chave))


def historico(request, objeto):
    return paginar(request, AtualizacaoCadastro.objects.filter(municipio=request.municipio, objeto=objeto).select_related('autor').order_by('-criado', '-id'), 'historico')


def registrar(request, objeto, acao, campos):
    AtualizacaoCadastro.objects.create(municipio=request.municipio, objeto=objeto, autor=request.user, acao=acao, campos=', '.join(campos)[:300])
    registrar_evento(request, acao, objeto=objeto)


def atendimentos_visiveis(request):
    consulta = Atendimento.objects.filter(municipio=request.municipio)
    if not tem_permissao(request.vinculo, 'sigilo.ver'):
        consulta = consulta.exclude(acompanhamento__sigiloso=True)
    return consulta.select_related('cidadao', 'acompanhamento__responsavel').annotate(data_ordenacao=Coalesce('acompanhamento__data_efetiva', 'criado')).order_by('-data_ordenacao', '-id')


def integracoes(request, pessoa=None, familia=None):
    secoes = []
    contratos = [
        ('SolicitacaoBeneficio', 'beneficios.ver', 'Benefícios eventuais', 'programas:beneficio_detalhe'),
        ('PedidoMaterial', 'materiais.ver', 'Materiais de construção', 'programas:pedido_detalhe'),
        ('ConcessaoVale', 'vale.ver', 'Vale-Alimentação', 'programas:vale_detalhe'),
    ]
    for modelo, permissao, titulo, rota in contratos:
        if tem_permissao(request.vinculo, permissao) and apps.is_installed('programas'):
            model = apps.get_model('programas', modelo)
            consulta = model.objects.filter(municipio=request.municipio)
            consulta = consulta.filter(Q(cidadao=pessoa) | Q(familia=pessoa.familia)) if pessoa else consulta.filter(familia=familia)
            relacao = {'SolicitacaoBeneficio': 'tipo', 'PedidoMaterial': 'material'}.get(modelo)
            if relacao:
                consulta = consulta.select_related(relacao)
            pagina = paginar(request, consulta.order_by(*model._meta.ordering), modelo.lower())
            links = {}
            for nome, numero in [('anterior', pagina.previous_page_number() if pagina.has_previous() else None), ('proxima', pagina.next_page_number() if pagina.has_next() else None)]:
                if numero:
                    parametros = request.GET.copy()
                    parametros[modelo.lower()] = numero
                    links[nome] = '?' + parametros.urlencode() + '#programas'
            secoes.append({'titulo': titulo, 'rota': rota, 'pagina': pagina, **links})
    return secoes


@sensitive_post_parameters('numero')
@municipal('cadastros.ver')
def inicio(request):
    busca_documento = BuscaDocumento(request.POST if request.method == 'POST' else None)
    resultado = None
    pesquisado = False
    if request.method == 'POST' and busca_documento.is_valid():
        pesquisado = True
        dados = busca_documento.cleaned_data
        filtro = {f"{dados['tipo']}_hash": indice(request.municipio.pk, dados['tipo'], dados['numero'])}
        resultado = ComplementoPessoa.objects.filter(municipio=request.municipio, **filtro).select_related('cidadao').first()
        registrar_evento(request, 'consulta_documento', objeto=resultado.cidadao_id if resultado else None)
        busca_documento = BuscaDocumento(initial={'tipo': dados['tipo']})
    q = request.GET.get('q', '').strip()[:100]
    pessoas = Cidadao.objects.filter(municipio=request.municipio).select_related('familia', 'complemento')
    if q:
        pessoas = pessoas.filter(Q(nome__icontains=q) | Q(familia__referencia__icontains=q))
    registrar_evento(request, 'consulta_cadastros')
    return render(request, 'cadastros/inicio.html', {'titulo': 'Cadastro geral', 'documento_form': busca_documento, 'pesquisado': pesquisado, 'resultado': resultado, 'pagina': paginar(request, pessoas.order_by('nome', 'id')), 'q': q})


@municipal('cadastros.ver')
def familias(request):
    q = request.GET.get('q', '').strip()[:100]
    consulta = Familia.objects.filter(municipio=request.municipio).select_related('complemento')
    if q:
        consulta = consulta.filter(Q(referencia__icontains=q) | Q(complemento__bairro__icontains=q) | Q(complemento__territorio__icontains=q))
    registrar_evento(request, 'consulta_familias')
    return render(request, 'cadastros/familias.html', {'titulo': 'Famílias', 'pagina': paginar(request, consulta.order_by('referencia', 'id')), 'q': q})


@municipal('cadastros.ver')
def pessoa(request, pk):
    pessoa = get_object_or_404(Cidadao.objects.select_related('familia'), pk=pk, municipio=request.municipio)
    complemento = ComplementoPessoa.objects.filter(cidadao=pessoa, municipio=request.municipio).first()
    registrar_evento(request, 'consulta_ficha_pessoa', objeto=pessoa.pk)
    return render(request, 'cadastros/pessoa.html', {'titulo': pessoa.nome, 'pessoa': pessoa, 'complemento': complemento, 'atendimentos': paginar(request, atendimentos_visiveis(request).filter(cidadao=pessoa) if tem_permissao(request.vinculo, 'atendimentos.ver') else Atendimento.objects.none(), 'atendimentos'), 'historico': historico(request, pessoa.pk), 'integracoes': integracoes(request, pessoa=pessoa)})


@municipal('cadastros.ver')
def familia(request, pk):
    familia = get_object_or_404(Familia, pk=pk, municipio=request.municipio)
    complemento = ComplementoFamilia.objects.filter(familia=familia, municipio=request.municipio).select_related('responsavel').first()
    membros = Cidadao.objects.filter(municipio=request.municipio, familia=familia).select_related('complemento').order_by('nome', 'id')
    pagina_membros = paginar(request, membros, 'membros')
    quantidade = pagina_membros.paginator.count
    per_capita = complemento.renda_mensal / quantidade if complemento and complemento.renda_mensal is not None and quantidade else None
    registrar_evento(request, 'consulta_ficha_familia', objeto=familia.pk)
    return render(request, 'cadastros/familia.html', {'titulo': familia.referencia, 'familia': familia, 'complemento': complemento, 'membros': pagina_membros, 'quantidade': quantidade, 'per_capita': per_capita, 'historico': historico(request, familia.pk), 'integracoes': integracoes(request, familia=familia)})


@sensitive_post_parameters()
@municipal('cadastros.ver', post='cadastros.editar')
def pessoa_form(request, pk=None):
    if not tem_permissao(request.vinculo, 'cadastros.editar'):
        return HttpResponseForbidden()
    pessoa = get_object_or_404(Cidadao, pk=pk, municipio=request.municipio) if pk else None
    complemento = ComplementoPessoa.objects.filter(cidadao=pessoa, municipio=request.municipio).first() if pessoa else None
    familia_id = uuid_seguro(request.GET.get('familia')) or (pessoa.familia_id if pessoa else None)
    familia = Familia.objects.filter(municipio=request.municipio, pk=familia_id).first() if familia_id else None
    initial = {'nome': pessoa.nome, 'familia_id': familia_id} if pessoa else {'familia_id': familia_id}
    form = PessoaForm(request.POST if request.method == 'POST' else None, instance=complemento, initial=initial)
    if request.method == 'POST' and form.is_valid():
        dados = form.cleaned_data
        familia = Familia.objects.filter(pk=dados['familia_id'], municipio=request.municipio).first()
        if familia is None:
            form.add_error(None, 'Selecione uma família deste município pela busca.')
        elif pessoa and familia.pk != pessoa.familia_id and ComplementoFamilia.objects.filter(municipio=request.municipio, responsavel=pessoa).exists():
            form.add_error(None, 'Atualize a referência responsável da família anterior antes de transferir esta pessoa.')
        else:
            try:
                with transaction.atomic():
                    if pessoa:
                        pessoa = Cidadao.objects.select_for_update().get(pk=pessoa.pk, municipio=request.municipio)
                        pessoa.nome, pessoa.familia = dados['nome'], familia
                        pessoa.save(update_fields=['nome', 'familia'])
                    else:
                        pessoa = Cidadao.objects.create(municipio=request.municipio, familia=familia, nome=dados['nome'])
                    complemento = form.save(commit=False)
                    complemento.municipio, complemento.cidadao = request.municipio, pessoa
                    campos = ['nascimento', 'telefone', 'parentesco', 'atualizado']
                    for tipo in ['cpf', 'nis']:
                        if dados[tipo]:
                            setattr(complemento, f'{tipo}_hash', indice(request.municipio.pk, tipo, dados[tipo]))
                            setattr(complemento, f'{tipo}_ultimos', dados[tipo][-4:])
                            campos.extend([f'{tipo}_hash', f'{tipo}_ultimos'])
                    complemento.save(update_fields=None if complemento._state.adding else campos)
                    registrar(request, pessoa.pk, 'pessoa_atualizada' if pk else 'pessoa_criada', form.changed_data)
                messages.success(request, 'Cadastro individual salvo.')
                return redirect('cadastros:pessoa', pk=pessoa.pk)
            except IntegrityError:
                form.add_error(None, 'Já existe cadastro com este CPF ou NIS no município. Faça a busca por documento antes de continuar.')
    return render(request, 'cadastros/form.html', {'titulo': 'Atualizar cidadão' if pk else 'Cadastrar cidadão', 'form': form, 'selecao': 'familia', 'selecionado': familia, 'pessoa': pessoa, **contexto_selecao(request, 'familia')})


@sensitive_post_parameters()
@municipal('cadastros.ver', post='cadastros.editar')
def familia_form(request, pk=None):
    if not tem_permissao(request.vinculo, 'cadastros.editar'):
        return HttpResponseForbidden()
    familia = get_object_or_404(Familia, pk=pk, municipio=request.municipio) if pk else None
    complemento = ComplementoFamilia.objects.filter(familia=familia, municipio=request.municipio).first() if familia else None
    responsavel_id = uuid_seguro(request.GET.get('responsavel')) or (complemento.responsavel_id if complemento else None)
    responsavel_atual = Cidadao.objects.filter(pk=responsavel_id, familia=familia, municipio=request.municipio).first() if responsavel_id and familia else None
    form = FamiliaForm(request.POST if request.method == 'POST' else None, municipio=request.municipio, instance=complemento, initial={'referencia': familia.referencia, 'responsavel_id': responsavel_atual.pk if responsavel_atual else None} if familia else None)
    if request.method == 'POST' and form.is_valid():
        responsavel_id = form.cleaned_data['responsavel_id']
        responsavel = Cidadao.objects.filter(pk=responsavel_id, familia=familia, municipio=request.municipio).first() if responsavel_id and familia else None
        if responsavel_id and not responsavel:
            form.add_error(None, 'O responsável deve integrar esta família. Confira a seleção.')
        else:
            if familia:
                familia = Familia.objects.select_for_update().get(pk=familia.pk, municipio=request.municipio)
                familia.referencia = form.cleaned_data['referencia']
                familia.save(update_fields=['referencia'])
            else:
                familia = Familia.objects.create(municipio=request.municipio, referencia=form.cleaned_data['referencia'])
            complemento = form.save(commit=False)
            complemento.municipio, complemento.familia, complemento.responsavel = request.municipio, familia, responsavel
            complemento.save()
            registrar(request, familia.pk, 'familia_atualizada' if pk else 'familia_criada', form.changed_data)
            messages.success(request, 'Ficha familiar salva.')
            return redirect('cadastros:familia', pk=familia.pk)
    return render(request, 'cadastros/form.html', {'titulo': 'Atualizar família' if pk else 'Cadastrar família', 'form': form, 'familia': familia, 'selecao': 'responsavel' if familia else None, 'selecionado': responsavel_atual, **(contexto_selecao(request, 'responsavel', familia) if familia else {})})


@municipal('atendimentos.ver')
def atendimentos(request):
    q = request.GET.get('q', '').strip()[:100]
    consulta = atendimentos_visiveis(request)
    if q:
        consulta = consulta.filter(Q(cidadao__nome__icontains=q) | Q(unidade__icontains=q) | Q(encaminhamento__icontains=q))
    registrar_evento(request, 'consulta_atendimentos')
    return render(request, 'cadastros/atendimentos.html', {'titulo': 'Atendimentos', 'pagina': paginar(request, consulta), 'q': q})


@municipal('atendimentos.ver')
def atendimento(request, pk):
    registro = get_object_or_404(atendimentos_visiveis(request), pk=pk)
    acompanhamento = AcompanhamentoAtendimento.objects.filter(atendimento=registro, municipio=request.municipio).first()
    nota = NotaTecnica.objects.filter(acompanhamento=acompanhamento, municipio=request.municipio).first() if acompanhamento and tem_permissao(request.vinculo, 'sigilo.ver') else None
    registrar_evento(request, 'consulta_atendimento', objeto=registro.pk)
    return render(request, 'cadastros/atendimento.html', {'titulo': 'Ficha de atendimento', 'registro': registro, 'acompanhamento': acompanhamento, 'nota': nota, 'historico': historico(request, registro.pk)})


@sensitive_post_parameters()
@municipal('atendimentos.ver', post='atendimentos.editar')
def atendimento_form(request, pk=None):
    if not tem_permissao(request.vinculo, 'atendimentos.editar'):
        return HttpResponseForbidden()
    registro = get_object_or_404(atendimentos_visiveis(request), pk=pk) if pk else None
    acompanhamento = AcompanhamentoAtendimento.objects.filter(atendimento=registro, municipio=request.municipio).first() if registro else None
    autorizado_sigilo = tem_permissao(request.vinculo, 'sigilo.ver')
    editar_sigilo = autorizado_sigilo and tem_permissao(request.vinculo, 'sigilo.editar')
    cidadao_id = uuid_seguro(request.GET.get('cidadao')) or (registro.cidadao_id if registro else None)
    pessoa = Cidadao.objects.filter(pk=cidadao_id, municipio=request.municipio).first() if cidadao_id else None
    initial = {'cidadao_id': cidadao_id}
    if registro:
        initial.update(unidade=registro.unidade, encaminhamento=registro.encaminhamento)
    if acompanhamento and autorizado_sigilo:
        nota = NotaTecnica.objects.filter(acompanhamento=acompanhamento, municipio=request.municipio).first()
        initial['nota_tecnica'] = nota.texto if nota else ''
    form = AtendimentoForm(request.POST if request.method == 'POST' else None, instance=acompanhamento, municipio=request.municipio, sigilo=autorizado_sigilo, initial=initial)
    if autorizado_sigilo and not editar_sigilo:
        form.fields['nota_tecnica'].disabled = True
        form.fields['sigiloso'].disabled = True
    if request.method == 'POST' and form.is_valid():
        pessoa = Cidadao.objects.filter(pk=form.cleaned_data['cidadao_id'], municipio=request.municipio).first()
        if not pessoa:
            form.add_error(None, 'Selecione um cidadão deste município.')
        else:
            if registro:
                registro = Atendimento.objects.select_for_update().get(pk=registro.pk, municipio=request.municipio)
                registro.cidadao, registro.unidade, registro.encaminhamento = pessoa, form.cleaned_data['unidade'], form.cleaned_data['encaminhamento']
                registro.save(update_fields=['cidadao', 'unidade', 'encaminhamento'])
            else:
                registro = Atendimento.objects.create(municipio=request.municipio, cidadao=pessoa, unidade=form.cleaned_data['unidade'], encaminhamento=form.cleaned_data['encaminhamento'])
            acompanhamento = form.save(commit=False)
            acompanhamento.municipio, acompanhamento.atendimento = request.municipio, registro
            if not acompanhamento.responsavel_id:
                acompanhamento.responsavel = request.user
            acompanhamento.save()
            if editar_sigilo:
                NotaTecnica.objects.update_or_create(acompanhamento=acompanhamento, municipio=request.municipio, defaults={'texto': form.cleaned_data['nota_tecnica']})
            registrar(request, registro.pk, 'atendimento_atualizado' if pk else 'atendimento_criado', form.changed_data)
            messages.success(request, 'Atendimento salvo.')
            return redirect('cadastros:atendimento', pk=registro.pk)
    return render(request, 'cadastros/form.html', {'titulo': 'Atualizar atendimento' if pk else 'Novo atendimento', 'form': form, 'selecao': 'cidadao', 'selecionado': pessoa, 'registro': registro, **contexto_selecao(request, 'cidadao')})
