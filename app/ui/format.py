"""Labels and number formatting shared by every page."""

from mock491.mockgen.world import TENANTS

# status -> (label, st.badge color, icon). Status always shows icon + label, never color alone.
STATUS = {
    "auto_approved": ("Auto-approved", "green", ":material/check_circle:"),
    "approved": ("Approved", "blue", ":material/verified:"),
    "pending_review": ("Needs review", "orange", ":material/schedule:"),
    "rejected": ("Rejected", "red", ":material/block:"),
}

# issue code -> (short label, what it means for the reviewer)
ISSUES = {
    "vkn_missing": ("No VKN", "No tax number was found, so this record was matched to a company "
                    "by name only. Check that the match below is the right company."),
    "vkn_checksum": ("Invalid VKN", "The tax number fails its checksum, most likely a typo. The "
                     "record was matched by name; check that the match below is right."),
    "currency_assumed": ("Currency assumed", "No currency was written next to the amount, so "
                         "TRY was assumed. Check the amount's currency in the source."),
    "date_missing": ("No date", "No document date was found."),
}  # fmt: skip

DOC_TYPES = {"contract": "Contract", "invoice": "Invoice"}


def tenant_label(tenant_id: str) -> str:
    """'HOLDING_ENERJI_AS' -> 'Enerji' (falls back to the id for unknown tenants)."""
    name = TENANTS.get(tenant_id)
    return name.removeprefix("Örnek Holding ").removesuffix(" A.Ş.") if name else tenant_id


def status_label(status: str) -> str:
    return STATUS.get(status, (status,))[0]


def issue_label(code: str) -> str:
    return ISSUES.get(code, (code,))[0]


def text(value) -> str:
    """Display text for a possibly missing value (None or pandas NaN -> '')."""
    return "" if value is None or value != value else str(value)


def money(value: float | None, currency: str = "₺") -> str:
    """Compact amount: ₺56.99M, ₺812.4K, ₺950."""
    if value is None:
        return "–"
    for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= size:
            return f"{currency}{value / size:.2f}".rstrip("0").rstrip(".") + suffix
    return f"{currency}{value:,.0f}"


def amount(value: float, currency: str) -> str:
    """Full amount in its own currency: 3,989,000.00 TRY."""
    return f"{value:,.2f} {currency}"


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n} {word if n == 1 else many or word + 's'}"
