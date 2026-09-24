"""Catalogo de productos para armar la lista de compras.

Responsabilidad unica: ofrecer los productos que la gente pone en una lista de
supermercado, agrupados como los agrupa una gondola.

Las categorias salen del arbol real de categorias que publica Carrefour
(`/api/catalog_system/pub/category/tree/2`), agrupadas para una lista de
compras: sus once rubros de perfumeria o sus diez de almacen sirven para navegar
un catalogo de miles de articulos, no para anotar lo que falta en casa.

Lo que se guarda aca no son productos concretos sino **lo que se busca**: "leche
entera", no "Leche Entera La Serenisima 1 L". Que marca y que envase se comparan
lo deciden `nucleo/marca.py` y `nucleo/formato.py` con lo que cada cadena tenga
ese dia, y el usuario puede cambiarlos despues.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Categoria:
    """Un rubro de la gondola, con los productos que se suelen anotar de el."""

    clave: str
    nombre: str
    icono: str
    productos: tuple[str, ...]

    def etiqueta_de(self, producto: str) -> str:
        """Como se muestra un producto en el menu."""
        return producto[:1].upper() + producto[1:]


CATEGORIAS: tuple[Categoria, ...] = (
    Categoria(
        clave="almacen",
        nombre="Almacen",
        icono="🥫",
        productos=(
            "aceite girasol",
            "aceite de oliva",
            "arroz",
            "fideos",
            "harina",
            "azucar",
            "sal fina",
            "vinagre",
            "polenta",
            "lentejas",
            "porotos",
            "garbanzos",
            "pure de tomate",
            "tomate triturado",
            "atun",
            "arvejas",
            "choclo",
            "mayonesa",
            "ketchup",
            "mostaza",
            "caldo",
            "aceitunas",
        ),
    ),
    Categoria(
        clave="desayuno",
        nombre="Desayuno y merienda",
        icono="☕",
        productos=(
            "yerba mate",
            "cafe molido",
            "cafe instantaneo",
            "te",
            "cacao",
            "mate cocido",
            "galletitas",
            "galletitas de agua",
            "tostadas",
            "cereales",
            "mermelada",
            "dulce de leche",
            "miel",
            "edulcorante",
        ),
    ),
    Categoria(
        clave="lacteos",
        nombre="Lacteos y frescos",
        icono="🥛",
        productos=(
            "leche entera",
            "leche descremada",
            "yogur",
            "yogur bebible",
            "queso crema",
            "queso cremoso",
            "queso rallado",
            "queso en fetas",
            "manteca",
            "crema de leche",
            "huevos",
            "ricota",
            "jamon cocido",
            "salchichas",
            "tapas de empanadas",
        ),
    ),
    Categoria(
        clave="bebidas",
        nombre="Bebidas",
        icono="🥤",
        productos=(
            "agua mineral",
            "agua saborizada",
            "soda",
            "coca cola",
            "gaseosa lima limon",
            "jugo",
            "cerveza",
            "vino tinto",
            "vino blanco",
            "fernet",
        ),
    ),
    Categoria(
        clave="frutas",
        nombre="Frutas y verduras",
        icono="🍎",
        productos=(
            "banana",
            "manzana",
            "naranja",
            "limon",
            "papa",
            "cebolla",
            "tomate",
            "zanahoria",
            "lechuga",
            "zapallo",
            "ajo",
            "morron",
            "palta",
            "batata",
        ),
    ),
    Categoria(
        clave="carnes",
        nombre="Carnes",
        icono="🥩",
        productos=(
            "carne picada",
            "milanesas",
            "pollo entero",
            "pechuga de pollo",
            "asado",
            "bife de chorizo",
            "nalga",
            "pescado",
            "chorizo",
        ),
    ),
    Categoria(
        clave="panaderia",
        nombre="Panaderia y congelados",
        icono="🍞",
        productos=(
            "pan lactal",
            "pan rallado",
            "medialunas",
            "prepizza",
            "papas congeladas",
            "hamburguesas",
            "helado",
            "verduras congeladas",
        ),
    ),
    Categoria(
        clave="limpieza",
        nombre="Limpieza",
        icono="🧽",
        productos=(
            "detergente",
            "lavandina",
            "jabon en polvo",
            "suavizante",
            "limpiador de pisos",
            "rollo de cocina",
            "papel higienico",
            "servilletas",
            "esponja",
            "bolsas de residuos",
            "desodorante de ambiente",
            "limpiavidrios",
            "trapo de piso",
        ),
    ),
    Categoria(
        clave="perfumeria",
        nombre="Perfumeria",
        icono="🧴",
        productos=(
            "shampoo",
            "acondicionador",
            "jabon de tocador",
            "pasta dental",
            "cepillo de dientes",
            "desodorante",
            "alcohol en gel",
            "toallitas femeninas",
            "papel tissue",
            "algodon",
        ),
    ),
)


CATEGORIA_POR_CLAVE = {categoria.clave: categoria for categoria in CATEGORIAS}


def todos_los_productos() -> tuple[str, ...]:
    """Todos los terminos del catalogo, sin repetir."""
    vistos: list[str] = []
    for categoria in CATEGORIAS:
        for producto in categoria.productos:
            if producto not in vistos:
                vistos.append(producto)
    return tuple(vistos)


def categoria_de(producto: str) -> Categoria | None:
    """En que categoria esta un producto. None si se escribio a mano."""
    for categoria in CATEGORIAS:
        if producto in categoria.productos:
            return categoria
    return None
