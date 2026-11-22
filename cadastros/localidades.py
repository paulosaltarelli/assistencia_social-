"""Referências públicas de logradouros, sem dados pessoais de moradores."""
from collections import defaultdict
from functools import lru_cache
from hashlib import sha256
from importlib.resources import files
import json


CODIGO_IBGE = '3157336'
CIDADE = 'Santa Cruz de Minas'


def cidade_do_catalogo(municipio):
    return bool(municipio and municipio.nome.strip().casefold() == CIDADE.casefold())


@lru_cache(maxsize=1)
def catalogo_municipal():
    recurso = files('cadastros').joinpath('dados', 'catalogo_santa_cruz_de_minas.json')
    with recurso.open(encoding='utf-8') as arquivo:
        dados = json.load(arquivo)
    cidade = dados['municipio']
    if str(cidade['codigo_ibge']) != CODIGO_IBGE or cidade['uf'] != 'MG' or cidade['nome'] != CIDADE:
        raise ValueError('O arquivo de logradouros pertence a outro município.')
    return dados


def pares_e_bairros(municipio):
    if not cidade_do_catalogo(municipio):
        return {}, []
    dados = catalogo_municipal()
    fontes = {fonte['id'] for fonte in dados['fontes']}
    bairros = {b['nome'] for b in dados['bairros'] if b.get('nome') and b.get('fonte_id') in fontes}
    pares = {}
    for item in dados['logradouros']:
        rua, bairro = item.get('logradouro'), item.get('bairro')
        if not rua or not bairro or item.get('fonte_id') not in fontes:
            continue
        chave = sha256(f'{rua}\n{bairro}'.encode()).hexdigest()[:20]
        pares[chave] = {'logradouro': rua, 'bairro': bairro}
        bairros.add(bairro)
    return pares, sorted(bairros, key=str.casefold)


def distribuir_enderecos(pares):
    grupos = defaultdict(list)
    for par in pares.values():
        grupos[par['bairro']].append(par)
    grupos_ordenados = [sorted(grupos[bairro], key=lambda p: p['logradouro'].casefold())
                        for bairro in sorted(grupos, key=str.casefold)]
    # Uma rua de cada bairro por rodada, sem recombinar nomes de fontes distintas.
    return [grupo[i] for i in range(max(map(len, grupos_ordenados), default=0))
            for grupo in grupos_ordenados if i < len(grupo)]


def fontes_dos_enderecos():
    dados = catalogo_municipal()
    ids = {p.get('fonte_id') for p in dados['logradouros'] if p.get('logradouro') and p.get('bairro')}
    return [fonte for fonte in dados['fontes'] if fonte['id'] in ids]
