"""Expense categories: classify() sorts one booking into WealthView's own categories (first matching rule wins).

Pure functions, no files, no network. Used by gls_block.py and bookings.py (flow model)."""
from __future__ import annotations
import hashlib, logging, re
from functools import lru_cache
from typing import Callable

from ...common.config import setting
from ...common.types.bookings import BookingRow
log = logging.getLogger(__name__)

# ------------------------------------------------------- expense categories
# Order matters: the first matching rule wins.  Everything unknown ends up in ONE bucket: "Sonstiges".
CAT_RULES = [
    ("Housing & Utilities", r"wohnungsverwalt|hausgeld|hausverwalt|\bweg\d|vattenfall|\bstrom\b|gasag|wasser|rundfunk|beitragsservice|grundsteuer|nebenkosten|heizung|energie|miete\b"),
    ("Home & Renovation", r"w[aä]rmepump|haushaltsger|matratze|handwerk|sanit[aä]r|maler|reparatur|schl[uü]ssel|hausmeister|ikea|obi\b|bauhaus|hornbach|elektro|installat|dachdecker|tischler|baumarkt"),
    ("Travel", r"rent a car|enterprise rent|camper|ferry|f[aä]hre|sixt rent|europcar|hertz|hotel|airbnb|booking\.com|lufthansa|qatar air|ryanair|easyjet|eurowings|transavia|reise|hostel|expedia|flug|urlaub|ferien|duty free|airport|rail europe|sncf|trainline|blablacar|resort|pension"),
    ("Insurance", r"versicherung|huk|axa\b|ergo\b|r\+v|debeka|signal iduna|haftpflicht|hausrat|krankenkasse|\bmkk\b|\bbkk\b|\btk\b|\baok\b|barmer|techniker krank"),
    ("Groceries", r"\brewe\b|\bedeka\b|\blidl\b|\baldi\b|\bnetto\b|\bpenny\b|alnatura|\bdenn.?s\b|bio company|kaufland|dm[- ]drog|dm-drogerie|rossmann|budni|metzger|fleisch|schlachter|b[aä]cker|baeck|sp[aä]ti|kiosk|supermarkt|biomarkt|lebensmittel|wochenmarkt|marktstand|gem[uü]se|obst|hofladen"),
    ("Dining & Delivery", r"wolt|lieferando|uber eats|restaurant|\brest\b|caf[eé]|pizz|burger|sushi|coffee|starbucks|bistro|imbiss|gastro|\bbar\b|brauhaus|brewhouse|br[aä]u\b|braeu|hofbraeu|kebab|kebap|d[oö]ner|ramen|\brice\b|bakery|taverna|bbq|sumup|pizzeria|trattoria|\beis\b|gelato|kfc|mcdonald|curry|kantine|cateri|zettle|burger king"),
    ("Transport", r"\bdb\b|db vertrieb|bahn|bvg|\bvbb\b|\buber\b|taxi|\bbolt\b|flix|\bshell\b|\baral\b|\besso\b|circle k|total service|\btank|parken|parkhaus|\bsixt\b|\bmiles\b|share now|free2move|\blime\b|\btier\b|mobilit|\bauto\b|kfz"),
    ("Health", r"apotheke|arzt|zahn|praxis|klinik|physio|optik|brille|gesundheit|medico"),
    ("Subscriptions & Digital", r"netflix|spotify|disney|apple|google|youtube|openai|anthropic|claude|github|microsoft|adobe|icloud|dropbox|bitwarden|patreon|steam|valve|nordvpn|nordsec|proton|strato|telekom|vodafone|\bo2\b|1&1|cyberport|media ?markt|saturn|notebooksbilliger|alternate|conrad"),
    ("Shopping", r"amazon|amzn|zalando|otto\b|ebay|h&m|decathlon|galeria|klarna|libri|fnac|parf[uü]merie|floristen|shopping|kleidung|deutsche post|reservix|geschenk|versand|onlinehandel|\bpayPal\b"),
    ("Leisure & Sport", r"kino|fitness|gym|urban sports|eventim|ticket|playstation|xbox|nintendo|theater|museum|schwimm|freizeit|sport|club|konzert|festival|yoga|reservix"),
    ("Donations & Memberships", r"e\.v\.|spende|\bverein|mitglied|greenpeace|\bwwf\b|unicef"),
    ("Fees & Taxes", r"finanzamt|steuer|geb[uü]hr|entgelt|kontof[uü]hrung|bankgeb|zinsen|mahn|abschluss per|vorabpauschale|gls gemeinschaftsbank|gls beitrag|bezirk|landkreis|beh[oö]rde|rechtsanw|steuerberat|notar|anwalt|ordnungsamt|bezirkskasse|stadtkasse|landeskasse|kreiskasse|bundesamt|justiz"),
    ("Cash", r"geldautomat|bargeld|auszahlung|atm\b|sparkasse|volksbank|cash withdrawal"),
    ("Family & Private", r"darlehen|darlehnen|taschengeld|unterhalt|privat|r[uü]ckzahlung"),
]


@lru_cache(maxsize=1)
def category_patterns() -> list[tuple[str, re.Pattern[str]]]:
    """Compiled CAT_RULES, built on first use (not at import), with two extension points from config.json:
    category_extra = [{"pattern": "<regex>", "category": "<category>"}] is OR-ed into that category's own rule, so it has exactly the
    precedence a built-in pattern of that category has; category_rules (older) = [[category, pattern]] is appended after the built-ins."""
    extra: dict[str, list[str]] = {}
    for e in setting("category_extra", []) or []:
        if not isinstance(e, dict):
            log.warning("category_extra: entry ignored (not an object)")
            continue
        pat, cat = str(e.get("pattern") or "").strip(), str(e.get("category") or "").strip()
        pat = re.sub(r"^(?:\(\?[aiLmsux]+\))+", "", pat)           # leading inline flags: matching is case-insensitive anyway
        if not pat or not cat:
            continue
        try:
            re.compile(pat)
        except re.error as exc:
            log.warning("category_extra: pattern ignored (%s)", exc)
            continue
        extra.setdefault(cat, []).append(pat)
    rules = []
    for c, p in CAT_RULES:
        rules.append((c, "|".join([p] + extra.pop(c, []))))
    for c, pats in extra.items():          # a category the built-ins do not have: its own rule at the end
        rules.append((c, "|".join(pats)))
    rules += [(c, p) for c, p in setting("category_rules", [])]
    return [(c, re.compile(p, re.I)) for c, p in rules]


# hints from the bank's own category (GLS "Kategorie") when our rules find nothing
GLS_CAT_MAP = [
    (r"lebensmittel|supermarkt|bio", "Groceries"), (r"gastronomie|restaurant|caf", "Dining & Delivery"),
    (r"gesundheit|apotheke|arzt", "Health"), (r"versicherung|krankenkasse|vereine", "Insurance"),
    (r"beh[oö]rden|steuern|geb[uü]hren|konto", "Fees & Taxes"), (r"haushaltsger|baumarkt|wohnen|einrichtung", "Home & Renovation"),
    (r"telefon|mobilfunk|computer|software|abo", "Subscriptions & Digital"), (r"technik|kaufhaus|paketdienste|versand|onlinehandel|amazon|bekleidung|mode", "Shopping"),
    (r"reise|urlaub|hotel|flug", "Travel"), (r"freizeit|sport|kultur|unterhaltung", "Leisure & Sport"),
    (r"verkehr|auto|tanken|bahn|mobilit", "Transport"), (r"bargeld|geldautomat", "Cash"),
]
GLS_CAT_RX = [(c, re.compile(p, re.I)) for p, c in GLS_CAT_MAP]
FOREIGN_RX = re.compile(r"\b(" + "|".join("AUT BEL BGR CHE CYP CZE DNK ESP EST FIN FRA GBR GRC HRV HUN IRL ISL ITA LTU LUX LVA MLT NLD NOR POL PRT ROU SVK SVN SWE TUR USA CAN MEX BRA ARG CHL JPN CHN KOR THA IND ARE QAT EGY MAR ZAF AUS NZL SGP MYS IDN VNM PHL ISR".split()) + r")\b")
INVEST_RX = re.compile(r"world ?fund|feeder|wiwin", re.I)      # public brands; own holdings go in config.json -> invest_extra


@lru_cache(maxsize=8)
def _invest_rx(extra: tuple[str, ...]) -> re.Pattern[str]:
    if not extra:
        return INVEST_RX
    return re.compile("|".join([INVEST_RX.pattern] + [re.escape(x) for x in extra]), re.I)


def invest_rx() -> re.Pattern[str]:
    """INVEST_RX plus the names in config.json -> invest_extra (list of strings, matched literally, any case)."""
    extra = setting("invest_extra", []) or []
    return _invest_rx(tuple(str(x).strip() for x in extra if str(x).strip()))
PERSON_RX = re.compile(r"^[A-ZÄÖÜ][\wäöüß.\-']+( [A-ZÄÖÜ][\wäöüß.\-']+){1,3}$")
COMPANY_RX = re.compile(r"gmbh|\bag\b|\bkg\b|\bug\b|\bse\b|e\.v\.|\bltd|b\.v\.|\binc|s\.a\.|\bco\b|bank|kasse|amt\b|shop|service|versicherung|verwaltung", re.I)
SONSTIGES = "Sonstiges"


# ------------------------------------------------------- your own corrections (v1.15)
# Stored in the database (tables cat_rules / cat_overrides), loaded by the refresh before the bookings are classified.
# Order: one booking's own correction > merchant rule > keyword rule > the built-in rules above.
merchant_resolver: Callable[[BookingRow], str] | None = None      # set by bookings.py (merchant_and_domain lives there; this avoids an import cycle)
_USER: dict[str, object] = dict(merchant={}, text=[], over={})


def override_key(r: BookingRow) -> str:
    """Stable key of ONE booking (account, date, amount, payee, purpose), used for single-booking corrections."""
    s = f"{r['account']}|{r['date'].isoformat()}|{r['amount']:.2f}|{r['counterparty'][:30]}|{r['purpose'][:80]}"
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def set_user_rules(rules: list[tuple[str, str, str]], overrides: dict[str, str]) -> None:
    """rules = [(kind 'merchant'|'text', pattern, category)]; overrides = {override_key: category}. Replaces what was loaded before."""
    merchant: dict[str, str] = {}
    text: list[tuple[str, re.Pattern[str]]] = []
    for kind, pattern, cat in rules:
        p = (pattern or "").strip()
        if not p or not cat:
            continue
        if kind == "merchant":
            merchant[p.lower()] = cat
        else:
            text.append((cat, re.compile(re.escape(p), re.I)))
    _USER.update(merchant=merchant, text=text, over=dict(overrides))


def classify(r: BookingRow) -> str:
    over = _USER["over"]
    if over:
        c = over.get(override_key(r))        # type: ignore[attr-defined]
        if c:
            return str(c)
    mer = _USER["merchant"]
    if mer and merchant_resolver:
        c = mer.get(merchant_resolver(r).strip().lower())    # type: ignore[attr-defined]
        if c:
            return str(c)
    txt = _USER["text"]
    if txt:
        t = " ".join([r["counterparty"], r["purpose"][:160]])
        for c, rx in txt:        # type: ignore[attr-defined]
            if rx.search(t):
                return str(c)
    return _builtin(r)


def _builtin(r: BookingRow) -> str:
    t = " ".join([r["counterparty"], r["purpose"][:160], r["typ"], r["cat"]])
    for c, rx in category_patterns():
        if rx.search(t):
            return c
    for c, rx in GLS_CAT_RX:
        if rx.search(r["cat"]):
            return c
    if r["kind"] == "card" and FOREIGN_RX.search(r["purpose"]) and " DEU " not in r["purpose"]:
        return "Travel"                      # card payment abroad = travel spending
    cp = r["counterparty"].strip()
    if r["kind"] == "giro" and cp and PERSON_RX.match(cp) and not COMPANY_RX.search(cp):
        return "Family & Private"            # transfer to a private person
    return SONSTIGES


def sector_key(s: str | None) -> str:
    """One spelling for a sector name ('Real Estate' -> 'realestate'); "" when there is none. Used by research and analytics."""
    k = str(s or "").strip().lower().replace(" ", "_")
    return {"real_estate": "realestate"}.get(k, k)
