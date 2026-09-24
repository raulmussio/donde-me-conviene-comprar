"""Puntuacion de parecido entre lo que pidio el usuario y lo que devuelve la API.

Responsabilidad unica: dado un ItemLista y una lista de Ofertas candidatas,
ordenarlas y decidir cual representa mejor al item.

Esta capa existe porque los buscadores de las cadenas son generosos: pedir
"leche" en Carrefour devuelve "Pepitas artesanales dulce de leche" en el primer
puesto. Sin filtro propio, la comparacion de precios compara cosas distintas,
que es la unica forma de que la app mienta.
"""

from __future__ import annotations

import math
import statistics

from nucleo.formato import FORMATO_LIBRE, Formato
from nucleo.modelos import ItemLista, Oferta
from nucleo.texto import modificadores_ajenos, tokenizar, tokenizar_ordenado

# Un candidato que no alcanza este puntaje se descarta: preferimos decir "no lo
# encontre en Dia" antes que cotizar el producto equivocado.
UMBRAL_ACEPTACION = 0.55

# Pesos del puntaje final. Suman 1.0.
PESO_COBERTURA = 0.45  # cuantos tokens del pedido aparecen en el producto
PESO_POSICION = 0.25  # que tan al principio del nombre aparece lo que pediste
PESO_ENVASE = 0.15  # que tan parecido es el tamano al pedido
PESO_PRECISION = 0.15  # penaliza nombres inflados de palabras ajenas

# Solo compiten entre si los candidatos que estan a menos de este margen del
# mejor puntaje de esa cadena. Ver `elegir_mejor`.
MARGEN_DE_COMPETENCIA = 0.10

# Un candidato cuyo precio por unidad cae por debajo de esta fraccion de la
# mediana del resto se considera un registro obsoleto, no una oferta. Ver
# `descartar_atipicos`.
FACTOR_ATIPICO = 0.35

# La deteccion de atipicos necesita suficientes candidatos para que la mediana
# signifique algo.
MINIMO_PARA_ATIPICOS = 4

# Tope de envases por item. Evita que un envase diminuto se proponga como
# solucion a un pedido grande ("1 kg" resuelto con 20 sobres de 50 g).
MAXIMO_ENVASES = 8


def puntuar(item: ItemLista, oferta: Oferta) -> float:
    """Parecido entre el pedido y una oferta concreta, 0..1."""
    pedidos = tokenizar(item.texto)
    if not pedidos:
        return 0.0
    ofrecidos = tokenizar(f"{oferta.nombre} {oferta.marca or ''}")
    if not ofrecidos:
        return 0.0

    presentes = {token for token in pedidos if _aparece(token, ofrecidos)}
    cobertura = len(presentes) / len(pedidos)

    # Sin cobertura casi total el resto no importa: "dulce de leche" cubre
    # "leche" pero agrega un sustantivo que cambia el producto.
    if cobertura < 0.99:
        return cobertura * PESO_COBERTURA

    # El producto trae una palabra que cambia lo que es. "Leche chocolatada" no
    # es leche y "Detergente para ropa" no es detergente de vajilla, por mas que
    # el nombre empiece igual y comparta todas las palabras del pedido.
    if modificadores_ajenos(
        item.texto, pedidos, f"{oferta.nombre} {oferta.marca or ''}"
    ):
        return PESO_COBERTURA * 0.5

    # Unidad incompatible con la pedida: es otra forma del producto, no otro
    # tamano. Quien pide "leche 1 L" no quiere leche en polvo de 800 g por mas
    # que el nombre coincida palabra por palabra.
    if item.unidad_objetivo and oferta.unidad and oferta.unidad != item.unidad_objetivo:
        return PESO_COBERTURA * 0.5

    precision = len(presentes) / len(ofrecidos)
    # La precision cruda castiga demasiado los nombres largos y descriptivos,
    # asi que se aplana: lo que importa es que no sea *otro* producto.
    precision = min(1.0, precision * 2.0)

    return (
        PESO_COBERTURA
        + PESO_POSICION * _parecido_posicion(pedidos, oferta)
        + PESO_ENVASE * _parecido_envase(item, oferta)
        + PESO_PRECISION * precision
    )


def _parecido_posicion(pedidos: set[str], oferta: Oferta) -> float:
    """Que tan al principio del nombre aparece lo que se pidio, 0..1.

    En los supermercados el tipo de producto encabeza el nombre y lo que sigue
    lo especifica: "Leche Ilolay Proteina 1 L". Cuando la palabra pedida aparece
    despues de otra, casi siempre es un ingrediente y no el producto:
    "Chocolate con leche", "Arroz con leche", "Batidor de leche", "Extractor de
    leche". Sin esta senal esos cuatro puntuan igual que la leche de verdad,
    porque todos contienen la palabra que se busco.
    """
    ordenados = tokenizar_ordenado(f"{oferta.nombre} {oferta.marca or ''}")
    if not ordenados:
        return 0.0

    posiciones = [
        indice
        for indice, token in enumerate(ordenados)
        if token in pedidos or _aparece(token, pedidos)
    ]
    if not posiciones:
        return 0.0
    # La primera aparicion es la que manda: alcanza con que el nombre empiece
    # por lo pedido para que sea el producto y no una mencion de paso.
    return 1.0 / (1.0 + min(posiciones))


def _aparece(token: str, ofrecidos: set[str]) -> bool:
    """True si el token del pedido esta en el producto, admitiendo plural y raiz."""
    if token in ofrecidos:
        return True
    # Tolerancia a plural y a variantes cortas ("fideo"/"fideos",
    # "galletita"/"galletitas"), sin caer en coincidencias de 3 letras.
    for otro in ofrecidos:
        if len(token) >= 5 and (otro.startswith(token) or token.startswith(otro)):
            if abs(len(otro) - len(token)) <= 3:
                return True
    return False


def _parecido_envase(item: ItemLista, oferta: Oferta) -> float:
    """Que tan cerca esta el envase del tamano pedido, 0..1.

    Si el usuario no pidio tamano, no penalizamos: devolvemos un valor neutro
    para no favorecer arbitrariamente al envase mas grande ni al mas chico.
    """
    if not item.magnitud_objetivo or not item.unidad_objetivo:
        return 0.5
    if not oferta.magnitud or oferta.unidad != item.unidad_objetivo:
        return 0.0
    razon = min(oferta.magnitud, item.magnitud_objetivo) / max(
        oferta.magnitud, item.magnitud_objetivo
    )
    return razon


def unidades_necesarias(formato: Formato, oferta: Oferta) -> int:
    """Cuantos envases hay que comprar para cubrir el formato de referencia.

    Si se compara 1 kg y el envase es de 500 g, hacen falta 2. Comparar el
    precio del envase sin este ajuste hace ganar sistematicamente a la cadena
    que vende el formato mas chico, que es justo al reves de lo que conviene.
    """
    if formato.es_libre:
        return 1
    if not oferta.magnitud or oferta.unidad != formato.unidad:
        return 1
    if oferta.magnitud >= formato.magnitud:
        return 1
    # Un envase que entra en el formato es un envase, aunque sea algo menor: un
    # pote de 480 g es la presentacion de medio kilo de esa marca, y proponer
    # comprar dos para "llegar" a 500 g duplicaria el precio sin motivo.
    if formato.contiene(oferta):
        return 1
    necesarias = math.ceil(formato.magnitud / oferta.magnitud)
    return max(1, min(necesarias, MAXIMO_ENVASES))


def costo_efectivo(formato: Formato, oferta: Oferta) -> float:
    """Lo que cuesta cubrir el formato con esa oferta, contando envases enteros."""
    return oferta.precio * unidades_necesarias(formato, oferta)


def descartar_atipicos(candidatos: list[Oferta]) -> list[Oferta]:
    """Saca de la lista los precios que no pueden ser reales.

    Los catalogos arrastran fichas viejas que nunca se dieron de baja y que
    conservan el precio de hace anios. En Coto conviven hoy un arroz de 1 kg a
    $1.770 y otro, con nombre casi igual, a $78,90. Tomar el segundo como el
    precio de la cadena no seria un descuento: seria un error.

    El corte es relativo a la mediana de los propios candidatos, no un monto
    fijo, para que siga funcionando cuando los precios cambien.

    La comparacion se hace **dentro de cada unidad por separado**. Mezclarlas
    rompia el criterio de la peor manera: buscando "leche" en ChangoMas los
    candidatos son chocolates por gramo, cremas por mililitro y un extractor de
    leche de $241.999 por unidad. La mediana de esa mezcla daba $14.430, y la
    unica leche de verdad, a $2.889 el litro, quedaba debajo del piso y se
    descartaba por "vieja". Despues ganaba un chocolate de 30 g porque era el
    mas barato que sobrevivia.
    """
    por_unidad: dict[str | None, list[Oferta]] = {}
    for oferta in candidatos:
        por_unidad.setdefault(oferta.unidad, []).append(oferta)

    descartados: set[int] = set()
    for grupo in por_unidad.values():
        if len(grupo) < MINIMO_PARA_ATIPICOS:
            continue
        referencias = [_referencia(o) for o in grupo]
        validas = [valor for valor in referencias if valor is not None]
        if len(validas) < MINIMO_PARA_ATIPICOS:
            continue
        piso = statistics.median(validas) * FACTOR_ATIPICO
        for oferta, valor in zip(grupo, referencias):
            if valor is not None and valor < piso:
                descartados.add(id(oferta))

    return [oferta for oferta in candidatos if id(oferta) not in descartados]


def _referencia(oferta: Oferta) -> float | None:
    """Valor con el que se compara una oferta contra otra: precio por unidad."""
    return oferta.precio_por_unidad if oferta.precio_por_unidad else oferta.precio


def puntuar_todos(item: ItemLista, candidatos: list[Oferta]) -> list[Oferta]:
    """Copia los candidatos con su puntaje ya calculado.

    El acuerdo de formato lo necesita: desempata por que tan bien representan al
    pedido los productos de cada tamano, y sin puntaje ese desempate no existe.
    """
    return [_con_puntaje(oferta, puntuar(item, oferta)) for oferta in candidatos]


def hay_agotado(candidatos: list[Oferta]) -> bool:
    """True si algun candidato representaba el pedido pero figura sin stock."""
    return any(
        not oferta.disponible and oferta.puntaje >= UMBRAL_ACEPTACION
        for oferta in candidatos
    )


def elegir_mejor(
    item: ItemLista,
    candidatos: list[Oferta],
    *,
    formato: Formato = FORMATO_LIBRE,
    maximo_alternativas: int = 6,
) -> tuple[Oferta | None, list[Oferta]]:
    """Devuelve (mejor oferta, alternativas) para un item, dentro de un formato.

    "Mejor" es el candidato mas barato entre los que superan el umbral de
    parecido *y* entran en el formato acordado, no el mas parecido: una vez que
    sabemos que el producto y el tamano son los correctos, lo que decide es el
    precio.

    El formato filtra, pero no es una condicion excluyente. Si ninguna oferta de
    la cadena entra en el, se vuelve a considerar todas contando cuantos envases
    harian falta: es preferible decir "aca lo cubris con dos paquetes de 500 g"
    antes que declarar que la cadena no tiene el producto.
    """
    puntuados: list[Oferta] = []
    for oferta in candidatos:
        if oferta.precio <= 0:
            continue
        puntaje = puntuar(item, oferta)
        if puntaje <= 0:
            continue
        puntuados.append(_con_puntaje(oferta, puntaje))

    if not puntuados:
        return None, []

    # Lo agotado se puntua igual, para poder distinguir despues "no lo tienen"
    # de "en tu zona esta sin stock", pero no compite por ser elegido.
    aceptables = [
        o for o in puntuados if o.puntaje >= UMBRAL_ACEPTACION and o.disponible
    ]
    puntuados.sort(key=lambda o: (-o.puntaje, costo_efectivo(formato, o)))

    if not aceptables:
        # Nada supera el umbral: no elegimos nada, pero mostramos lo que hubo
        # para que el usuario decida si alguno le sirve.
        return None, puntuados[:maximo_alternativas]

    # Solo compiten los candidatos que representan igual de bien lo pedido. Sin
    # esto, cualquier producto que apenas superara el umbral ganaba por ser el
    # mas barato: buscando "leche" en ChangoMas, un chocolate de 30 g a $922 le
    # ganaba a la leche de 1 L a $2.889.
    mejor_puntaje = max(o.puntaje for o in aceptables)
    competidores = [
        o for o in aceptables if o.puntaje >= mejor_puntaje - MARGEN_DE_COMPETENCIA
    ]

    en_formato = [o for o in competidores if formato.contiene(o)]
    # El respaldo se limita a la misma unidad: que falte el envase exacto
    # justifica comprar dos paquetes de 500 g, no cotizar un chocolate de 30 g
    # cuando lo que se compara son litros de leche.
    if en_formato:
        elegibles = en_formato
    elif formato.es_libre:
        elegibles = competidores
    else:
        elegibles = [o for o in competidores if o.unidad == formato.unidad]

    # Las fichas viejas se buscan recien aca, entre los productos que ya son el
    # mismo producto en el mismo tamano. Hacerlo antes comparaba cosas que no se
    # comparan: pedir "banana" trae la fruta a $2.499 el kilo y galletitas de
    # banana a $22.500 el kilo, y contra esa mediana la fruta parecia un precio
    # imposible y se descartaba.
    elegibles = descartar_atipicos(elegibles)

    if not elegibles:
        return None, puntuados[:maximo_alternativas]

    # Entre los que representan al producto correcto decide el costo de cubrir
    # el pedido, no el precio de la etiqueta.
    elegibles.sort(key=lambda o: (costo_efectivo(formato, o), -o.puntaje))
    mejor = elegibles[0]
    alternativas = [o for o in puntuados if o is not mejor][:maximo_alternativas]
    return mejor, alternativas


def _con_puntaje(oferta: Oferta, puntaje: float) -> Oferta:
    """Copia la oferta fijando su puntaje (Oferta es inmutable)."""
    return Oferta(
        cadena=oferta.cadena,
        nombre=oferta.nombre,
        marca=oferta.marca,
        precio=oferta.precio,
        precio_lista=oferta.precio_lista,
        ean=oferta.ean,
        url=oferta.url,
        imagen=oferta.imagen,
        disponible=oferta.disponible,
        magnitud=oferta.magnitud,
        unidad=oferta.unidad,
        puntaje=puntaje,
    )
