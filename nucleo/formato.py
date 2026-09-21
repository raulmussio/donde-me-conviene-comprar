"""Acuerdo de un formato de envase comun entre las cinco cadenas.

Responsabilidad unica: decidir, para un item de la lista, que tamano de envase
se va a comparar en todas las cadenas.

Sin esta capa cada cadena elige su envase por su cuenta y la comparacion deja de
significar algo. Pedir "coca cola" devolvia una botella de 220 ml en Carrefour,
una de 600 ml en Coto y una de 354 ml en ChangoMas, y el "mas barato" terminaba
siendo el envase mas chico, no el mejor precio. Peor todavia: "queso crema"
traia un paquete de Cheetos de 43 gramos compitiendo contra potes de 290.

La regla es elegir el formato que **mas cadenas tienen**, y recien despues
comparar precios dentro de ese formato. Si el usuario escribio el tamano, manda
el usuario y no hay nada que acordar.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

from nucleo.modelos import ItemLista, Oferta
from nucleo.texto import formatear_envase

LOGGER = logging.getLogger(__name__)

# Dos envases se consideran el mismo formato si sus tamanos no difieren mas que
# este factor. Cubre las diferencias reales entre marcas (900 ml contra 1 L,
# 480 g contra 500 g, 190 g contra 200 g) sin mezclar tamanos que el cliente ve
# como distintos: con 1.3 una Coca de 2,25 L entraba a competir contra las de
# 1,75 L de las otras cadenas, que es un 28% mas de producto por un precio que
# se mostraba como si fuera comparable.
TOLERANCIA = 1.2

# Un formato solo compite por ser el elegido si su mejor coincidencia esta a
# menos de este margen de la mejor de todas. Ver `_opciones`.
#
# Es mas estricto que el margen con que se elige el producto dentro de un
# formato, porque aca se decide que se compara y no cual se compra. Con 0.10,
# "Banana Chips Dulces San Juanita 100 g" quedaba justo adentro: empieza con la
# palabra buscada, asi que la senal de posicion no lo separa de la fruta, y solo
# lo distingue el arrastre de palabras ajenas.
MARGEN_DE_CALIDAD = 0.08

# Un producto cuenta como representativo del pedido si esta a menos de este
# margen del mejor candidato. Es mas estricto que el anterior porque no decide
# si un formato es admisible, sino cual de los admisibles es el comun.
MARGEN_REPRESENTATIVO = 0.05


@dataclass(frozen=True)
class Formato:
    """El tamano de envase con el que se compara un item en todas las cadenas."""

    magnitud: float | None
    unidad: str | None
    # True cuando el formato representa a los productos que **no** declaran
    # envase. Es distinto de "cualquier envase": es una eleccion deliberada de
    # comparar lo fresco. Ver `_opciones`.
    a_granel: bool = False

    @property
    def es_libre(self) -> bool:
        """True cuando no se acordo nada y sirve cualquier envase."""
        return not self.a_granel and (not self.magnitud or not self.unidad)

    @property
    def etiqueta(self) -> str:
        if self.a_granel:
            return "fresco, por unidad o peso"
        if self.es_libre:
            return "cualquier envase"
        return formatear_envase(self.magnitud, self.unidad)

    def contiene(self, oferta: Oferta) -> bool:
        """True si el envase de la oferta entra en este formato."""
        if self.a_granel:
            return oferta.magnitud is None
        if self.es_libre:
            return True
        if not oferta.magnitud or oferta.unidad != self.unidad:
            return False
        mayor = max(oferta.magnitud, self.magnitud)
        menor = min(oferta.magnitud, self.magnitud)
        return mayor / menor <= TOLERANCIA


FORMATO_LIBRE = Formato(magnitud=None, unidad=None)

# Los productos frescos no declaran envase: un alcaucil se vende por unidad o
# por peso y su nombre es solo "Alcaucil". Sin este formato, el consenso solo
# podia elegir entre los envasados y terminaba comparando corazones de alcaucil
# en frasco a $18.890 cuando lo que se pidio vale $4.999 en la verduleria.
FORMATO_A_GRANEL = Formato(magnitud=None, unidad=None, a_granel=True)


def del_item(item: ItemLista) -> Formato | None:
    """El formato que pidio el usuario, si escribio un tamano."""
    if item.magnitud_objetivo and item.unidad_objetivo:
        return Formato(magnitud=item.magnitud_objetivo, unidad=item.unidad_objetivo)
    return None


def consensuar(
    item: ItemLista, candidatos_por_cadena: dict[str, list[Oferta]]
) -> Formato:
    """Elige el formato con el que se va a comparar este item.

    Gana el tamano presente en mas cadenas y, entre esos, el que tiene mas
    productos que son de verdad lo que se pidio. Es decir, el formato comun: el
    paquete de azucar de 1 kg y no el sobre de 250 g, el pote de queso crema de
    290 g y no el de medio kilo.
    """
    pedido = del_item(item)
    if pedido:
        return pedido

    opciones = _opciones(candidatos_por_cadena)
    if not opciones:
        return FORMATO_LIBRE
    return opciones[0]


def opciones_ordenadas(
    item: ItemLista, candidatos_por_cadena: dict[str, list[Oferta]]
) -> list[Formato]:
    """Todos los formatos que ofrecen las cadenas, del mas comun al menos.

    Es lo que alimenta el selector de la interfaz para que el usuario pueda
    corregir el formato elegido sin volver a consultar los sitios.
    """
    opciones = _opciones(candidatos_por_cadena)
    pedido = del_item(item)
    if pedido and not any(_mismo(pedido, opcion) for opcion in opciones):
        opciones.insert(0, pedido)
    return opciones


def _opciones(candidatos_por_cadena: dict[str, list[Oferta]]) -> list[Formato]:
    """Formatos candidatos, ordenados por cuantas cadenas los tienen."""
    todos = [
        (cadena, oferta)
        for cadena, ofertas in candidatos_por_cadena.items()
        for oferta in ofertas
    ]
    con_envase = [par for par in todos if par[1].magnitud and par[1].unidad]

    # Cada tamano distinto es un formato candidato. Se agrupan los equivalentes
    # dentro de la tolerancia para no tratar 900 ml y 1 L como dos mundos.
    vistos: list[Formato] = []
    for _, oferta in con_envase:
        propuesto = Formato(magnitud=oferta.magnitud, unidad=oferta.unidad)
        if not any(_mismo(propuesto, existente) for existente in vistos):
            vistos.append(propuesto)

    # Lo fresco compite como un formato mas: si son mas las cadenas que ofrecen
    # el producto sin envase que las que lo ofrecen envasado, gana lo fresco.
    if any(oferta.magnitud is None for _, oferta in todos):
        vistos.append(FORMATO_A_GRANEL)

    if not vistos:
        return []

    # Cuantas cadenas tienen un formato decide, pero solo entre los que
    # realmente representan lo pedido. Sin este filtro la cobertura le ganaba al
    # producto correcto: pedir "banana" elegia los chips de banana de 100 g,
    # porque estan en las cinco cadenas, sobre la fruta fresca, que esta en
    # cuatro.
    mejor_global = max((oferta.puntaje for _, oferta in todos), default=0.0)

    puntuados: list[tuple[float, float, float, float, Formato]] = []
    descartados: list[tuple[float, float, float, float, Formato]] = []
    for formato in vistos:
        cadenas: set[str] = set()
        puntajes: list[float] = []
        for cadena, oferta in todos:
            if formato.contiene(oferta):
                cadenas.add(cadena)
                puntajes.append(oferta.puntaje)
        if not cadenas:
            continue
        calidad = sum(puntajes) / len(puntajes) if puntajes else 0.0
        # Cuantos productos de ese tamano son de verdad lo que se pidio. Es la
        # medida de que tan comun es el formato, y decide el desempate.
        representativos = sum(
            1 for puntaje in puntajes if puntaje >= mejor_global - MARGEN_REPRESENTATIVO
        )
        # Orden: en cuantas cadenas esta, cuantos productos representativos
        # tiene, la calidad media y por ultimo el envase mas grande.
        #
        # Hace falta contar productos porque la cobertura se satura: con varios
        # tamanos presentes en las cinco cadenas, desempatar por calidad media
        # elige mal, porque esa media baja cuanto mas grande es el grupo. Para
        # "queso crema" elegia el de 500 g, con 29 productos, sobre el de 290 g,
        # que tiene 82 y es el que esta en toda gondola.
        #
        # Y hace falta contar solo los representativos, no todos, porque el
        # conteo crudo premia a los tamanos donde se juntan las variedades
        # raras: para "azucar" elegia el sobre de 250 g, que suma 32 productos
        # entre edulcorantes, azucar impalpable y azucar negra, sobre el paquete
        # de 1 kg, que es el que se compra.
        fila = (
            -float(len(cadenas)),
            -float(representativos),
            -round(calidad, 3),
            -(formato.magnitud or 0),
            formato,
        )
        if max(puntajes, default=0.0) >= mejor_global - MARGEN_DE_CALIDAD:
            puntuados.append(fila)
        else:
            descartados.append(fila)

    puntuados.sort(key=lambda fila: fila[:4])
    descartados.sort(key=lambda fila: fila[:4])
    # Los descartados igual se ofrecen al final del selector: son envases reales
    # y el usuario puede querer justamente ese.
    return [fila[4] for fila in puntuados] + [fila[4] for fila in descartados]


def _mismo(uno: Formato, otro: Formato) -> bool:
    """True si dos formatos son el mismo tamano dentro de la tolerancia."""
    if uno.unidad != otro.unidad:
        return False
    if not uno.magnitud or not otro.magnitud:
        return uno.magnitud == otro.magnitud
    mayor = max(uno.magnitud, otro.magnitud)
    menor = min(uno.magnitud, otro.magnitud)
    return mayor / menor <= TOLERANCIA


def agrupar_por_cadena(
    candidatos: dict[tuple[str, int], list[Oferta]], indice: int, cadenas: list[str]
) -> dict[str, list[Oferta]]:
    """Reordena los candidatos crudos a un diccionario por cadena, para un item."""
    salida: dict[str, list[Oferta]] = defaultdict(list)
    for cadena in cadenas:
        salida[cadena] = list(candidatos.get((cadena, indice)) or [])
    return dict(salida)
