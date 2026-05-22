from routes.conf_despesas import (
    _build_veiculo_aliases,
    _compile_veiculo_matchers,
    _match_veiculo_row,
)


def test_build_veiculo_aliases_avoids_generic_brand_when_model_exists():
    aliases = _build_veiculo_aliases('Carreta', 'Scania', 'R540', 'ABC1D23', None)

    assert 'SCANIA R540' in aliases
    assert 'R540' in aliases
    assert 'SCANIA' not in aliases


def test_match_veiculo_row_distinguishes_scania_r500_from_r540():
    veiculos = [
        {
            'veiculo_id': 1,
            'nome': 'Marcos Antonio Batista',
            'aliases': _build_veiculo_aliases('Carreta', 'Scania', 'R540', 'AAA1A11', None),
        },
        {
            'veiculo_id': 2,
            'nome': 'Waldir de Oliveira Lemes',
            'aliases': _build_veiculo_aliases('Carreta', 'Scania', 'R500', 'BBB2B22', None),
        },
    ]

    matchers = _compile_veiculo_matchers(veiculos)

    r540 = _match_veiculo_row('VEICULO CARRETA MODELO SCANIA R540', matchers)
    r500 = _match_veiculo_row('VEICULO CARRETA MODELO SCANIA R500', matchers)

    assert r540['veiculo_id'] == 1
    assert r540['nome'] == 'Marcos Antonio Batista'
    assert r500['veiculo_id'] == 2
    assert r500['nome'] == 'Waldir de Oliveira Lemes'


def test_match_veiculo_row_supports_model_only_categories():
    veiculos = [{
        'veiculo_id': 3,
        'nome': 'Valmir',
        'aliases': _build_veiculo_aliases('Truck', 'Mercedes', 'Actros 1620', 'CCC3C33', None),
    }]

    matchers = _compile_veiculo_matchers(veiculos)
    matched = _match_veiculo_row('VEICULO TRUCK MODELO ACTROS 1620', matchers)

    assert matched['veiculo_id'] == 3
