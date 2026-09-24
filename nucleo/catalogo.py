"""Catalogo de productos para armar la lista de compras.

Responsabilidad unica: ofrecer los productos que la gente pone en una lista de
supermercado, agrupados como los agrupa una gondola.

Las categorias no salen de una sola cadena sino del cruce de los arboles que
publican las cuatro que corren sobre VTEX (`/api/catalog_system/pub/category/tree/2`).
Cada una arma el suyo distinto: Carrefour separa "Desayuno y merienda" de
"Almacen", Dia los junta, Jumbo llama "Frescos" a lo que otra llama "Lacteos y
productos frescos". Quedarse con una sola dejaba afuera rubros enteros, asi que
se toman los que aparecen en varias y se agrupan para una lista de compras: sus
once subrubros de perfumeria sirven para navegar un catalogo de miles de
articulos, no para anotar lo que falta en casa.

Lo que se guarda aca no son productos concretos sino **lo que se busca**: "leche
entera", no "Leche Entera La Serenisima 1 L". Que marca y que envase se comparan
lo decide el usuario en el paso siguiente, sobre lo que cada cadena tenga ese
dia.
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
            "aceite de maiz",
            "vinagre",
            "arroz",
            "arroz integral",
            "fideos",
            "fideos guiseros",
            "tallarines",
            "harina",
            "harina leudante",
            "polenta",
            "pure de papas",
            "lentejas",
            "porotos",
            "garbanzos",
            "arvejas",
            "choclo",
            "pure de tomate",
            "tomate triturado",
            "salsa de tomate",
            "atun",
            "caballa",
            "sardinas",
            "aceitunas",
            "sal fina",
            "sal gruesa",
            "pimienta",
            "oregano",
            "mayonesa",
            "ketchup",
            "mostaza",
            "salsa golf",
            "caldo",
            "sopa",
            "pan rallado",
            "rebozador",
            "papas fritas",
            "palitos salados",
            "mani",
        ),
    ),
    Categoria(
        clave="desayuno",
        nombre="Desayuno y merienda",
        icono="☕",
        productos=(
            "yerba mate",
            "yerba mate sin palo",
            "mate cocido",
            "cafe molido",
            "cafe instantaneo",
            "cafe en granos",
            "te",
            "te de hierbas",
            "cacao en polvo",
            "chocolatada",
            "azucar",
            "edulcorante",
            "galletitas",
            "galletitas de agua",
            "galletitas dulces",
            "bizcochos",
            "tostadas",
            "cereales",
            "avena",
            "granola",
            "barritas de cereal",
            "mermelada",
            "dulce de leche",
            "dulce de membrillo",
            "miel",
            "alfajores",
            "chocolate",
            "budin",
            "magdalenas",
        ),
    ),
    Categoria(
        clave="lacteos",
        nombre="Lacteos y frescos",
        icono="🥛",
        productos=(
            "leche entera",
            "leche descremada",
            "leche en polvo",
            "yogur",
            "yogur bebible",
            "yogur griego",
            "queso crema",
            "queso cremoso",
            "queso port salut",
            "queso rallado",
            "queso en fetas",
            "muzzarella",
            "ricota",
            "manteca",
            "margarina",
            "crema de leche",
            "huevos",
            "flan",
            "postre",
            "jamon cocido",
            "jamon crudo",
            "salame",
            "mortadela",
            "salchichas",
            "tapas de empanadas",
            "tapas de tarta",
            "ravioles",
            "ñoquis",
            "levadura",
        ),
    ),
    Categoria(
        clave="carnes",
        nombre="Carnes y pescados",
        icono="🥩",
        productos=(
            "carne picada",
            "milanesas de carne",
            "nalga",
            "cuadrada",
            "bife de chorizo",
            "asado",
            "vacio",
            "matambre",
            "pollo entero",
            "pechuga de pollo",
            "pata muslo",
            "suprema",
            "carne de cerdo",
            "bondiola",
            "costillitas de cerdo",
            "chorizo",
            "morcilla",
            "salchicha parrillera",
            "pescado",
            "merluza",
            "salmon",
            "langostinos",
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
            "mandarina",
            "limon",
            "pera",
            "uva",
            "frutilla",
            "palta",
            "papa",
            "batata",
            "cebolla",
            "tomate",
            "zanahoria",
            "lechuga",
            "espinaca",
            "acelga",
            "zapallo",
            "zapallito",
            "calabaza",
            "brocoli",
            "choclo fresco",
            "ajo",
            "morron",
            "pepino",
            "apio",
            "puerro",
            "champignones",
            "ensalada",
            "nueces",
            "almendras",
            "pasas de uva",
        ),
    ),
    Categoria(
        clave="panaderia",
        nombre="Panaderia",
        icono="🍞",
        productos=(
            "pan lactal",
            "pan lactal integral",
            "pan de hamburguesa",
            "pan de pancho",
            "pan arabe",
            "medialunas",
            "facturas",
            "prepizza",
            "tapas de pizza",
            "bizcochuelo",
            "pionono",
            "grisines",
            "tortillas",
        ),
    ),
    Categoria(
        clave="congelados",
        nombre="Congelados",
        icono="🧊",
        productos=(
            "hamburguesas congeladas",
            "medallones de pollo",
            "nuggets",
            "papas congeladas",
            "bastones de muzzarella",
            "verduras congeladas",
            "milanesas de soja",
            "pizza congelada",
            "empanadas congeladas",
            "helado",
            "hielo",
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
            "coca cola zero",
            "gaseosa lima limon",
            "gaseosa naranja",
            "gaseosa pomelo",
            "tonica",
            "jugo",
            "jugo en polvo",
            "jugo exprimido",
            "bebida isotonica",
            "energizante",
            "agua tonica",
        ),
    ),
    Categoria(
        clave="alcohol",
        nombre="Con alcohol",
        icono="🍷",
        productos=(
            "cerveza",
            "cerveza rubia",
            "cerveza ipa",
            "vino tinto",
            "vino blanco",
            "malbec",
            "espumante",
            "sidra",
            "fernet",
            "vermut",
            "gin",
            "vodka",
            "whisky",
            "ron",
            "aperitivo",
        ),
    ),
    Categoria(
        clave="limpieza",
        nombre="Limpieza",
        icono="🧽",
        productos=(
            "detergente",
            "jabon liquido para ropa",
            "jabon en polvo",
            "suavizante",
            "quitamanchas",
            "lavandina",
            "limpiador de pisos",
            "limpiador de banio",
            "limpiavidrios",
            "limpiador de cocina",
            "desengrasante",
            "desodorante de ambiente",
            "insecticida",
            "rollo de cocina",
            "papel higienico",
            "servilletas",
            "esponja",
            "virulana",
            "trapo de piso",
            "trapo rejilla",
            "guantes de limpieza",
            "bolsas de residuos",
            "papel film",
            "papel aluminio",
        ),
    ),
    Categoria(
        clave="perfumeria",
        nombre="Perfumeria e higiene",
        icono="🧴",
        productos=(
            "shampoo",
            "acondicionador",
            "crema de peinar",
            "jabon de tocador",
            "jabon liquido para manos",
            "gel de ducha",
            "pasta dental",
            "cepillo de dientes",
            "enjuague bucal",
            "hilo dental",
            "desodorante",
            "antitranspirante",
            "crema corporal",
            "protector solar",
            "maquina de afeitar",
            "espuma de afeitar",
            "toallitas femeninas",
            "tampones",
            "protectores diarios",
            "algodon",
            "hisopos",
            "alcohol en gel",
            "panuelos descartables",
            "repelente",
        ),
    ),
    Categoria(
        clave="bebes",
        nombre="Bebes",
        icono="🍼",
        productos=(
            "panales",
            "toallitas humedas",
            "shampoo para bebe",
            "jabon para bebe",
            "crema para bebe",
            "oleo calcareo",
            "leche de formula",
            "papilla",
            "mamadera",
            "chupete",
        ),
    ),
    Categoria(
        clave="mascotas",
        nombre="Mascotas",
        icono="🐾",
        productos=(
            "alimento para perros",
            "alimento para gatos",
            "alimento humedo para perros",
            "alimento humedo para gatos",
            "piedritas sanitarias",
            "snacks para perros",
            "collar antipulgas",
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
