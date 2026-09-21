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

from nucleo.modelos import ItemLista, Oferta
from nucleo.texto import tokenizar

# Un candidato que no alcanza este puntaje se descarta: preferimos decir "no lo
# encontre en Dia" antes que cotizar el producto equivocado.
UMBRAL_ACEPTACION = 0.55

# Pesos del puntaje final. Suman 1.0.
PESO_COBERTURA = 0.60  # cuantos tokens del pedido aparecen en el producto
PESO_ENVASE = 0.25  # que tan parecido es el tamano al pedido
PESO_PRECISION = 0.15  # penaliza nombres inflados de palabras ajenas

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
        + PESO_ENVASE * _parecido_envase(item, oferta)
        + PESO_PRECISION * precision
    )


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


def unidades_necesarias(item: ItemLista, oferta: Oferta) -> int:
    """Cuantos envases hay que comprar para cubrir lo que pidio el usuario.

    Si pediste 1 kg y el envase es de 500 g, hacen falta 2. Comparar el precio
    del envase sin este ajuste hace ganar sistematicamente a la cadena que
    vende el formato mas chico, que es justo al reves de lo que conviene.
    """
    if not item.magnitud_objetivo or not item.unidad_objetivo:
        return 1
    if not oferta.magnitud or oferta.unidad != item.unidad_objetivo:
        return 1
    if oferta.magnitud >= item.magnitud_objetivo:
        return 1
    necesarias = math.ceil(item.magnitud_objetivo / oferta.magnitud)
    return max(1, min(necesarias, MAXIMO_ENVASES))


def costo_efectivo(item: ItemLista, oferta: Oferta) -> float:
    """Lo que cuesta cubrir el item con esa oferta, contando envases enteros."""
    return oferta.precio * unidades_necesarias(item, oferta)


def descartar_atipicos(candidatos: list[Oferta]) -> list[Oferta]:
    """Saca de la lista los precios que no pueden ser reales.

    Los catalogos arrastran fichas viejas que nunca se dieron de baja y que
    conservan el precio de hace anios. En Coto conviven hoy un arroz de 1 kg a
    $1.770 y otro, con nombre casi igual, a $78,90. Tomar el segundo como el
    precio de la cadena no seria un descuento: seria un error.

    El corte es relativo a la mediana de los propios candidatos, no un monto
    fijo, para que siga funcionando cuando los precios cambien.
    """
    if len(candidatos) < MINIMO_PARA_ATIPICOS:
        return candidatos

    referencias = [_referencia(o) for o in candidatos]
    validas = [valor for valor in referencias if valor is not None]
    if len(validas) < MINIMO_PARA_ATIPICOS:
        return candidatos

    piso = statistics.median(validas) * FACTOR_ATIPICO
    return [
        oferta
        for oferta, valor in zip(candidatos, referencias)
        if valor is None or valor >= piso
    ]


def _referencia(oferta: Oferta) -> float | None:
    """Valor con el que se compara una oferta contra otra: precio por unidad."""
    return oferta.precio_por_unidad if oferta.precio_por_unidad else oferta.precio


def elegir_mejor(
    item: ItemLista, candidatos: list[Oferta], *, maximo_alternativas: int = 4
) -> tuple[Oferta | None, list[Oferta]]:
    """Devuelve (mejor oferta, alternativas) para un item.

    "Mejor" es el candidato mas barato entre los que superan el umbral de
    parecido, no el mas parecido: una vez que sabemos que el producto es el
    correcto, lo que decide es el precio. Las alternativas se devuelven ya
    puntuadas para que la UI permita corregir a mano.
    """
    puntuados: list[Oferta] = []
    for oferta in candidatos:
        if not oferta.disponible or oferta.precio <= 0:
            continue
        puntaje = puntuar(item, oferta)
        if puntaje <= 0:
            continue
        puntuados.append(_con_puntaje(oferta, puntaje))

    if not puntuados:
        return None, []

    puntuados = descartar_atipicos(puntuados)
    if not puntuados:
        return None, []

    aceptables = [o for o in puntuados if o.puntaje >= UMBRAL_ACEPTACION]
    puntuados.sort(key=lambda o: (-o.puntaje, costo_efectivo(item, o)))

    if not aceptables:
        # Nada supera el umbral: no elegimos nada, pero mostramos lo que hubo
        # para que el usuario decida si alguno le sirve.
        return None, puntuados[:maximo_alternativas]

    # Entre los que representan al producto correcto decide el costo de cubrir
    # el pedido, no el precio de la etiqueta.
    aceptables.sort(key=lambda o: (costo_efectivo(item, o), -o.puntaje))
    mejor = aceptables[0]
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
