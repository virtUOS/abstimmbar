# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Word list for human-friendly room codes (ADR-0006).

Curated to be **ASCII-only and unproblematic in both German and English** —
no umlauts/ß, no words that are rude or misleading in either language. Most
are international/cognate nouns (animals, nature, music, food, objects) so a
code like ``tiger-komet-radio`` is easy to say, spell and remember on either
side. Keep entries lowercase, letters only, and unique.

With ~500 words a three-word code yields >10^8 combinations (more than the
old 8-digit numeric code); collisions are retried in ``Room.save``.
"""

WORDS = [
    # animals
    "tiger", "panda", "zebra", "koala", "lemur", "puma", "otter", "bison",
    "gecko", "koba", "delfin", "kobra", "krokodil", "leopard", "gorilla",
    "pinguin", "flamingo", "elefant", "giraffe", "kamel", "lama", "alpaka",
    "jaguar", "panther", "gepard", "wolf", "fuchs", "biber", "dachs", "igel",
    "hamster", "kanari", "papagei", "tukan", "pelikan", "kondor", "adler",
    "falke", "reiher", "storch", "kranich", "schwan", "delta", "walross",
    "seehund", "narwal", "orca", "krebs", "krabbe", "hummer", "auster",
    "koralle", "seestern", "medusa", "anemone", "salamander", "molch",
    "chamaeleon", "leguan", "python", "boa", "viper", "skorpion", "tarantel",
    "libelle", "hornisse", "hummel", "grille", "zikade", "kaefer", "marienkaefer",
    "termite", "ameise", "raupe", "falter", "motte", "forelle", "karpfen",
    "hecht", "barsch", "sardine", "makrele", "thunfisch", "rochen", "hai",
    "manta", "quokka", "wombat", "dingo", "kojote", "puma", "ozelot", "serval",
    # nature and geography
    "berg", "gipfel", "tal", "huegel", "klippe", "canyon", "fjord", "delta",
    "insel", "atoll", "riff", "lagune", "bucht", "strand", "duene", "wueste",
    "oase", "savanne", "tundra", "steppe", "prairie", "dschungel", "wald",
    "hain", "wiese", "moor", "sumpf", "quelle", "bach", "fluss", "strom",
    "see", "teich", "kanal", "wasserfall", "geysir", "vulkan", "krater",
    "lava", "magma", "gletscher", "eisberg", "lawine", "schlucht", "grotte",
    "hoehle", "tunnel", "pfad", "steig", "kamm", "grat", "plateau", "mesa",
    "stein", "fels", "kiesel", "sand", "lehm", "granit", "marmor", "quarz",
    "kristall", "achat", "opal", "topas", "jade", "bernstein", "diamant",
    # sky and space
    "sonne", "mond", "stern", "komet", "meteor", "planet", "galaxie", "nebel",
    "orbit", "rakete", "satellit", "sonde", "krater", "aurora", "zenit",
    "horizont", "polaris", "sirius", "wega", "kosmos", "quasar", "pulsar",
    "nova", "eklipse", "merkur", "venus", "mars", "jupiter", "saturn",
    "uranus", "neptun", "pluto", "titan", "phobos", "europa", "kallisto",
    # weather
    "wolke", "nebel", "regen", "schnee", "hagel", "sturm", "orkan", "brise",
    "wind", "boe", "blitz", "donner", "tau", "frost", "eis", "regenbogen",
    "monsun", "taifun", "zyklon", "tornado", "wirbel", "front", "klima",
    # colors and light
    "rot", "gelb", "gruen", "blau", "lila", "orange", "violett", "indigo",
    "azur", "tuerkis", "smaragd", "rubin", "koralle", "purpur", "magenta",
    "zyan", "ocker", "beige", "grau", "silber", "gold", "bronze", "kupfer",
    "platin", "prisma", "spektrum", "schatten", "funke", "flamme", "glut",
    "strahl", "laser", "neon", "kerze", "fackel", "lampe", "laterne", "leuchte",
    # music
    "tango", "disco", "opera", "piano", "cello", "banjo", "geige", "harfe",
    "fluete", "oboe", "fagott", "trompete", "posaune", "tuba", "gong", "trommel",
    "pauke", "rhythmus", "melodie", "akkord", "oktave", "sonate", "sinfonie",
    "ballade", "hymne", "kanon", "chor", "solo", "duett", "quartett", "note",
    "takt", "tempo", "forte", "piano", "vinyl", "radio", "studio", "buehne",
    # food and drink
    "mango", "melone", "kiwi", "banane", "orange", "zitrone", "limette",
    "kirsche", "pflaume", "aprikose", "pfirsich", "traube", "feige", "dattel",
    "kokos", "ananas", "papaya", "guave", "mandel", "walnuss", "kastanie",
    "haselnuss", "kakao", "kaffee", "tee", "honig", "zimt", "vanille", "ingwer",
    "pfeffer", "safran", "basilikum", "minze", "salbei", "thymian", "kuemmel",
    "pasta", "pizza", "risotto", "sushi", "tofu", "olive", "tomate", "gurke",
    "paprika", "kuerbis", "spinat", "brokkoli", "karotte", "kartoffel", "zwiebel",
    "knoblauch", "linse", "bohne", "erbse", "mais", "reis", "hafer", "gerste",
    "brezel", "waffel", "keks", "torte", "pudding", "sorbet", "praline",
    # objects and tools
    "motor", "turbine", "kolben", "ventil", "getriebe", "achse", "rad", "reifen",
    "anker", "kompass", "sextant", "fernrohr", "mikroskop", "prisma", "linse",
    "magnet", "spule", "batterie", "dynamo", "kabel", "antenne", "radar",
    "sonar", "roboter", "drohne", "sensor", "chip", "platine", "pixel",
    "hammer", "zange", "saege", "meissel", "feile", "bohrer", "schraube",
    "nagel", "leiter", "gabel", "loeffel", "messer", "teller", "tasse", "krug",
    "kanne", "kessel", "pfanne", "topf", "sieb", "waage", "uhr", "wecker",
    "pendel", "kompass", "globus", "atlas", "karte", "buch", "feder", "tinte",
    "pinsel", "palette", "staffelei", "leinwand", "rahmen", "spiegel", "vase",
    # transport
    "segel", "boot", "kutter", "yacht", "fregatte", "galeone", "kanu", "kajak",
    "floss", "faehre", "dampfer", "zug", "lok", "waggon", "tram", "bus",
    "roller", "vespa", "kutsche", "schlitten", "ballon", "zeppelin", "gleiter",
    "rakete", "kapsel", "shuttle", "rover", "traktor", "kran", "bagger",
    # buildings and places
    "turm", "burg", "schloss", "palast", "tempel", "pagode", "kuppel",
    "arena", "kolosseum", "forum", "agora", "basar", "markt", "hafen", "kai",
    "bruecke", "viadukt", "portal", "torbogen", "saeule", "arkade", "atrium",
    "veranda", "balkon", "terrasse", "kamin", "schmiede", "muehle", "scheune",
    "silo", "leuchtturm", "windmuehle", "obelisk", "pyramide", "mosaik",
    # abstract and calm
    "ruhe", "stille", "friede", "harmonie", "balance", "fokus", "klarheit",
    "energie", "impuls", "faktor", "vektor", "matrix", "formel", "logik",
    "muster", "raster", "gitter", "spirale", "welle", "puls", "echo", "resonanz",
    "kaskade", "fontaene", "quelle", "funke", "zenit", "aura", "nimbus",
    # plants
    "eiche", "buche", "birke", "ahorn", "linde", "ulme", "esche", "kiefer",
    "tanne", "fichte", "zeder", "zypresse", "palme", "bambus", "farn", "moos",
    "efeu", "klee", "distel", "nessel", "binse", "schilf", "lotus", "iris",
    "tulpe", "narzisse", "krokus", "lilie", "rose", "nelke", "veilchen",
    "aster", "dahlie", "malve", "mohn", "lavendel", "jasmin", "flieder",
    "magnolie", "kamelie", "orchidee", "kaktus", "sukkulent", "agave", "aloe",
]

# De-duplicate while keeping order (curated list may repeat across categories).
WORDS = list(dict.fromkeys(WORDS))
