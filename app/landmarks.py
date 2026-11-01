"""Curated Toronto landmarks. Questions about these never need a Nominatim lookup."""
import re

LANDMARKS = [
    {
        "name": "CN Tower",
        "aliases": ["cn tower", "the tower", "cn"],
        "lat": 43.6426, "lon": -79.3871,
        "fact": "it was the world's tallest free-standing structure for over 30 years, and you can walk around the outside ledge on the EdgeWalk",
    },
    {
        "name": "Union Station",
        "aliases": ["union station", "union"],
        "lat": 43.6453, "lon": -79.3806,
        "fact": "it opened in 1927 and is the busiest transit hub in Canada",
    },
    {
        "name": "St. Lawrence Market",
        "aliases": ["st lawrence market", "st. lawrence market", "saint lawrence market", "st lawrence", "lawrence market"],
        "lat": 43.6487, "lon": -79.3716,
        "fact": "the peameal bacon sandwich at Carousel Bakery is basically the official Toronto sandwich",
    },
    {
        "name": "Distillery District",
        "aliases": ["distillery district", "the distillery", "distillery"],
        "lat": 43.6503, "lon": -79.3596,
        "fact": "Gooderham and Worts was once the biggest distillery in the world, and the whole area is car-free cobblestone now",
    },
    {
        "name": "Kensington Market",
        "aliases": ["kensington market", "kensington"],
        "lat": 43.6547, "lon": -79.4005,
        "fact": "on Pedestrian Sundays in summer they close the streets to cars and it turns into a street party",
    },
    {
        "name": "Royal Ontario Museum",
        "aliases": ["royal ontario museum", "rom", "the rom"],
        "lat": 43.6677, "lon": -79.3948,
        "fact": "the giant crystal-shaped entrance was designed by Daniel Libeskind and opened in 2007",
    },
    {
        "name": "Art Gallery of Ontario",
        "aliases": ["art gallery of ontario", "ago", "the ago", "art gallery"],
        "lat": 43.6536, "lon": -79.3925,
        "fact": "Frank Gehry redesigned it, and he actually grew up a few blocks away",
    },
    {
        "name": "Casa Loma",
        "aliases": ["casa loma", "the castle"],
        "lat": 43.6780, "lon": -79.4094,
        "fact": "it's a real castle built in 1914 by Sir Henry Pellatt, and it shows up in a lot of movies, including X-Men",
    },
    {
        "name": "Nathan Phillips Square",
        "aliases": ["nathan phillips square", "nathan phillips", "city hall", "the toronto sign", "toronto sign"],
        "lat": 43.6525, "lon": -79.3835,
        "fact": "the pool turns into a free skating rink in winter, right in front of City Hall",
    },
    {
        "name": "Eaton Centre",
        "aliases": ["eaton centre", "eaton center", "the eaton centre", "eatons"],
        "lat": 43.6544, "lon": -79.3807,
        "fact": "look up inside, there's a flock of 60 fibreglass Canada geese hanging from the ceiling, by Michael Snow",
    },
    {
        "name": "Rogers Centre",
        "aliases": ["rogers centre", "rogers center", "skydome", "the dome", "blue jays stadium"],
        "lat": 43.6414, "lon": -79.3894,
        "fact": "when it opened as SkyDome in 1989 it was the first stadium with a fully retractable roof",
    },
    {
        "name": "Scotiabank Arena",
        "aliases": ["scotiabank arena", "scotiabank", "the arena", "acc", "air canada centre"],
        "lat": 43.6435, "lon": -79.3791,
        "fact": "it's home to both the Leafs and the Raptors, and it used to be a Canada Post sorting building",
    },
    {
        "name": "Hockey Hall of Fame",
        "aliases": ["hockey hall of fame", "hall of fame"],
        "lat": 43.6473, "lon": -79.3772,
        "fact": "it's inside an old Bank of Montreal building, and the staff swear it's haunted by a ghost named Dorothy",
    },
    {
        "name": "Ripley's Aquarium",
        "aliases": ["ripley's aquarium", "ripleys aquarium", "ripley's", "ripleys", "the aquarium", "aquarium"],
        "lat": 43.6424, "lon": -79.3860,
        "fact": "there's a moving walkway through a shark tunnel, so sharks swim right over your head",
    },
    {
        "name": "Harbourfront Centre",
        "aliases": ["harbourfront centre", "harbourfront", "harborfront", "the waterfront", "waterfront"],
        "lat": 43.6387, "lon": -79.3817,
        "fact": "there's almost always a free festival or concert going on along the lake there",
    },
    {
        "name": "Jack Layton Ferry Terminal",
        "aliases": ["ferry terminal", "jack layton ferry terminal", "the ferry", "ferry", "toronto islands", "the islands", "island ferry", "centre island"],
        "lat": 43.6402, "lon": -79.3754,
        "fact": "the ferry ride to the Islands gives you the best skyline view in the city for the price of a TTC fare",
    },
    {
        "name": "Graffiti Alley",
        "aliases": ["graffiti alley", "rush lane"],
        "lat": 43.6480, "lon": -79.3978,
        "fact": "it's officially called Rush Lane, and Rick Mercer filmed his famous rants walking down it",
    },
    {
        "name": "Chinatown",
        "aliases": ["chinatown", "china town", "spadina and dundas"],
        "lat": 43.6529, "lon": -79.3980,
        "fact": "it's one of the biggest Chinatowns in North America, centred on Spadina and Dundas",
    },
    {
        "name": "Yorkville",
        "aliases": ["yorkville", "bloor yorkville"],
        "lat": 43.6709, "lon": -79.3933,
        "fact": "in the sixties it was Canada's hippie capital, and Joni Mitchell played the coffee houses there",
    },
    {
        "name": "Pearson Airport",
        "aliases": ["pearson airport", "pearson", "the airport", "airport", "yyz"],
        "lat": 43.6777, "lon": -79.6248,
        "fact": "the UP Express train gets you from Union Station to Pearson in about 25 minutes, way faster than a cab",
    },
    {
        "name": "Billy Bishop Airport",
        "aliases": ["billy bishop airport", "billy bishop", "island airport", "toronto island airport"],
        "lat": 43.6287, "lon": -79.3962,
        "fact": "you get there through a pedestrian tunnel under the harbour, it's one of the few downtown airports in the world",
    },
    {
        "name": "University of Toronto",
        "aliases": ["university of toronto", "u of t", "uoft", "u of toronto", "uoft campus"],
        "lat": 43.6629, "lon": -79.3957,
        "fact": "insulin was discovered there in 1921",
    },
]

# Longest aliases first so "union station" wins over "union".
_ALIASES = sorted(
    ((alias, lm) for lm in LANDMARKS for alias in lm["aliases"]),
    key=lambda pair: -len(pair[0]),
)


def _normalize(text: str) -> str:
    text = text.lower().replace("’", "'").replace(".", "")
    return re.sub(r"\s+", " ", text)


def find_in_text(text: str):
    """Return the first landmark mentioned in the text, or None."""
    clean = _normalize(text)
    for alias, lm in _ALIASES:
        alias_clean = _normalize(alias)
        if re.search(r"(?<![a-z])" + re.escape(alias_clean) + r"(?![a-z])", clean):
            return lm
    return None
