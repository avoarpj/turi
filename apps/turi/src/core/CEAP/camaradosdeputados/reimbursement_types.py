CEAP_CATEGORIES = {
    # '<subcota>.<especificacaoSubcota>': [category, sub_category]
    '1.0': [1, 0],
    '2.0': [2, 0],
    '3.1': [3, 1],
    '3.2': [3, 2],
    '3.3': [3, 3],
    '3.4': [3, 4],
    '4.0': [4, 0],
    '5.0': [5, 0],
    '6.0': [6, 0],
    '7.0': [7, 0],
    '8.0': [8, 0],
    '9.0': [9, 7],
    '10.0': [10, 0],
    '11.0': [11, 0],
    '12.0': [12, 0],
    '13.0': [13, 0],
    '14.0': [14, 0],
    '15.0': [15, 8],
    '119.0': [15, 9],
    '120.0': [15, 8],
    '121.0': [15, 10],
    '122.0': [16, 0],
    '123.0': [17, 0],
    '137.9': [18, 0],
    '998.0': [9, 5],
    '999.0': [9, 6],
}

CEAP_CATEGORIES_STRUCTMAP = {
    (1, 0): (1, 0),
    (2, 0): (2, 0),
    (3, 1): (3, 1),
    (3, 2): (3, 2),
    (3, 3): (3, 3),
    (3, 4): (3, 4),
    (4, 0): (4, 0),
    (5, 0): (5, 0),
    (6, 0): (6, 0),
    (7, 0): (7, 0),
    (8, 0): (8, 0),
    (9, 0): (9, 7),
    (10, 0): (10, 0),
    (11, 0): (11, 0),
    (12, 0): (12, 0),
    (13, 0): (13, 0),
    (14, 0): (14, 0),
    (15, 0): (15, 8),
    (119, 0): (15, 9),
    (120, 0): (15, 8),
    (121, 0): (15, 10),
    (122, 0): (16, 0),
    (123, 0): (17, 0),
    (137, 9): (18, 0),
    (998, 0): (9, 5),
    (999, 0): (9, 6),
}

"""
Esse dicionário é somente uma tabela de tradução entre as categorias na Câmara dos Deputados para a categoria no Avoar.
Para obter as categorias do Avoar, consulte core/opendata/mandate.domain.go
Para obter a lista de categoria da câmara dos deputados, consulte a cópia da resposta deles em ./reimbursement_types.md
"""