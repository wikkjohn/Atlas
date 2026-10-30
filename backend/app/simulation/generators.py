"""Deterministic synthetic data generators.

Phase 2 uses the name generator for the demo seed; Phase 5 adds the application and
employee generators that drive simulation runs.

Every generator takes an explicit seed and uses its own `random.Random` instance (never the
global random state), so the same seed always produces the same data. Names are random
pairings of common given names and surnames; they describe no real person.
"""

import random
from collections.abc import Iterable

FIRST_NAMES = (
    "Aarav",
    "Abigail",
    "Adebayo",
    "Aiko",
    "Alejandro",
    "Amara",
    "Amelia",
    "Anders",
    "Ananya",
    "Arjun",
    "Astrid",
    "Beatriz",
    "Benjamin",
    "Camila",
    "Chen",
    "Chloe",
    "Daniel",
    "Daria",
    "Diego",
    "Elena",
    "Elif",
    "Emeka",
    "Emma",
    "Farah",
    "Felix",
    "Freya",
    "Gabriel",
    "Hana",
    "Haruto",
    "Hugo",
    "Ines",
    "Isaac",
    "Isabella",
    "Jakob",
    "Jia",
    "Jonas",
    "Kai",
    "Kavya",
    "Kenji",
    "Lars",
    "Layla",
    "Leon",
    "Lucas",
    "Lucia",
    "Mateo",
    "Maya",
    "Mei",
    "Mia",
    "Mohammed",
    "Nadia",
    "Noah",
    "Nora",
    "Olivia",
    "Omar",
    "Priya",
    "Rafael",
    "Rania",
    "Ren",
    "Rohan",
    "Sakura",
    "Samuel",
    "Sara",
    "Sebastian",
    "Sofia",
    "Tariq",
    "Theo",
    "Valentina",
    "Wei",
    "Yara",
    "Yusuf",
    "Zara",
    "Zoe",
)

LAST_NAMES = (
    "Abe",
    "Adeyemi",
    "Alvarez",
    "Andersson",
    "Bauer",
    "Becker",
    "Bennett",
    "Chan",
    "Chen",
    "Costa",
    "Das",
    "Dubois",
    "Ellis",
    "Fischer",
    "Fujita",
    "Garcia",
    "Goh",
    "Gupta",
    "Hansen",
    "Harris",
    "Hoffmann",
    "Ito",
    "Iyer",
    "Jensen",
    "Kato",
    "Khan",
    "Kim",
    "Koch",
    "Kumar",
    "Lee",
    "Lim",
    "Lopez",
    "Mehta",
    "Meyer",
    "Moreno",
    "Muller",
    "Nakamura",
    "Nair",
    "Ng",
    "Novak",
    "Okafor",
    "Okoye",
    "Park",
    "Patel",
    "Perez",
    "Quinn",
    "Rahman",
    "Reyes",
    "Richter",
    "Rossi",
    "Saito",
    "Santos",
    "Schmidt",
    "Schulz",
    "Shah",
    "Silva",
    "Suzuki",
    "Tan",
    "Tanaka",
    "Taylor",
    "Teo",
    "Torres",
    "Wagner",
    "Walker",
    "Wang",
    "Watanabe",
    "Weber",
    "Wong",
    "Yamamoto",
    "Yilmaz",
)


class SyntheticNameGenerator:
    def __init__(self, seed: int) -> None:
        self._random = random.Random(seed)

    def name(self) -> tuple[str, str]:
        return self._random.choice(FIRST_NAMES), self._random.choice(LAST_NAMES)

    def integer(self, low: int, high: int) -> int:
        return self._random.randint(low, high)


# --- Simulation generators --------------------------------------------------------------------

import hashlib  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from datetime import date  # noqa: E402

from app.modules.compliance.screening import SANCTIONS_LISTS  # noqa: E402

# Names on the synthetic watchlist used by WF-0001's sanctions screening (fictional).
WATCHLIST_NAMES = (
    "Darius Vantablack",
    "Morgana Ledgerworth",
    "Silas Offshore",
    "Vera Shellcompany",
)
DOCUMENT_PREFIX = {"passport": "P", "national_id": "N", "proof_of_address": "A"}


def case_random(seed: int, index: int, purpose: str) -> random.Random:
    """An independent, reproducible random stream for one case and purpose.

    String seeds are hashed with SHA-512 by `random.Random`, so this does not depend on
    PYTHONHASHSEED or on the order in which cases are processed.
    """
    return random.Random(f"{seed}:{index}:{purpose}")


def document_number(document_type: str, serial: int) -> str:
    body = f"{serial % 10**7:07d}"
    return f"{DOCUMENT_PREFIX[document_type]}{body}{sum(int(d) for d in body) % 10}"


@dataclass(frozen=True)
class SyntheticApplication:
    index: int
    kind: str  # the ApplicationMix category
    expected_outcome: str  # ground truth: "approved" or "rejected"
    arrival_offset_seconds: int
    document_delay_seconds: int | None  # None: no late documents (or never, if abandoned)
    payload: dict


SHOULD_REJECT = frozenset({"sanctions_hit", "forged_document", "underage", "abandoned_documents"})


class ApplicationGenerator:
    """Generates WF-0001 applications with known ground truth."""

    def __init__(
        self,
        seed: int,
        mix: dict[str, float],
        countries: list[str],
        arrival_window_seconds: int,
        document_delay_seconds: tuple[int, int],
        today: date,
        rules: dict[str, dict] | None = None,
    ) -> None:
        self.seed = seed
        # Per-country rules (Phase 28): when given, cases follow them; see `_one_by_rules`.
        self.rules = rules
        self.kinds = sorted(mix)
        self.weights = [mix[k] for k in self.kinds]
        self.countries = sorted(countries)
        self.window = arrival_window_seconds
        self.delay = document_delay_seconds
        self.today = today

    def generate(self, count: int) -> list[SyntheticApplication]:
        return [self._one(i) for i in range(count)]

    def generate_indices(self, indices: Iterable[int]) -> list[SyntheticApplication]:
        """The applications with these indices (a shard's): identical to `generate`'s."""
        return [self._one(i) for i in indices]

    def _one(self, index: int) -> SyntheticApplication:
        if self.rules is not None:
            return self._one_by_rules(index)
        rng = case_random(self.seed, index, "application")
        kind = rng.choices(self.kinds, weights=self.weights)[0]
        if kind == "sanctions_hit":
            name = rng.choice(WATCHLIST_NAMES)
        else:
            name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        age = rng.randint(14, 17) if kind == "underage" else rng.randint(19, 80)
        born = date(self.today.year - age, rng.randint(1, 12), rng.randint(1, 28))
        serial = rng.randint(0, 9_999_999)
        identity = {
            "document_type": "passport" if rng.random() < 0.6 else "national_id",
            "document_number": "",
            "name_on_document": name,
            "date_of_birth": born.isoformat(),
            "expiry_date": date(self.today.year + rng.randint(1, 9), 6, 30).isoformat(),
        }
        identity["document_number"] = document_number(identity["document_type"], serial)
        if kind == "forged_document":
            number = identity["document_number"]
            identity["document_number"] = number[:-1] + str((int(number[-1]) + 1) % 10)
        address = {
            "document_type": "proof_of_address",
            "document_number": document_number("proof_of_address", serial + 1),
            "name_on_document": name if kind != "name_mismatch" else name + "e",
        }
        documents = [identity]
        late = kind in ("missing_documents", "abandoned_documents")
        if not late:
            documents.append(address)
        payload = {
            "applicant_name": name,
            "date_of_birth": born.isoformat(),
            "country_code": rng.choice(self.countries),
            "account_type": "current" if rng.random() < 0.75 else "savings",
            "documents": documents,
            "politically_exposed": kind == "politically_exposed",
            "expected_monthly_deposits": rng.choice([60_000, 120_000])
            if kind == "politically_exposed"
            else rng.randint(0, 20_000),
            "_late_document": address if late else None,
        }
        return SyntheticApplication(
            index=index,
            kind=kind,
            expected_outcome="rejected" if kind in SHOULD_REJECT else "approved",
            arrival_offset_seconds=rng.randint(0, self.window),
            document_delay_seconds=rng.randint(*self.delay)
            if kind == "missing_documents"
            else None,
            payload=payload,
        )

    def _one_by_rules(self, index: int) -> SyntheticApplication:
        """An application that follows its country's rules, so its ground truth holds there:
        ages around that country's minimum age, an accepted identity document, a proof of
        address only where one is required (otherwise the identity document is the one that
        arrives late), and sanctioned names from the lists the country screens against."""
        rng = case_random(self.seed, index, "application")
        kind = rng.choices(self.kinds, weights=self.weights)[0]
        country = rng.choice(self.countries)
        rules = self.rules[country]  # type: ignore[index]
        if kind == "sanctions_hit":
            names = sorted({n for list_id in rules["lists"] for n in SANCTIONS_LISTS[list_id][1]})
            name = rng.choice(names).title()
        else:
            name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        minimum = rules["min_age"]
        # The year of birth alone sets the age to `age` or one less, depending on the day.
        age = (
            rng.randint(minimum - 3, minimum - 1)
            if kind == "underage"
            else rng.randint(minimum + 1, 80)
        )
        born = date(self.today.year - age, rng.randint(1, 12), rng.randint(1, 28))
        serial = rng.randint(0, 9_999_999)
        document_type = rng.choice(rules["identity_documents"])
        identity = {
            "document_type": document_type,
            "document_number": document_number(document_type, serial),
            "name_on_document": name,
            "date_of_birth": born.isoformat(),
            "expiry_date": date(self.today.year + rng.randint(1, 9), 6, 30).isoformat(),
        }
        if kind == "forged_document":
            number = identity["document_number"]
            identity["document_number"] = number[:-1] + str((int(number[-1]) + 1) % 10)
        address = {
            "document_type": "proof_of_address",
            "document_number": document_number("proof_of_address", serial + 1),
            "name_on_document": name if kind != "name_mismatch" else name + "e",
        }
        documents = [identity, address]
        late_kind = kind in ("missing_documents", "abandoned_documents")
        late = None
        if late_kind:
            # The document the country requires is the one that is missing.
            late = address if rules["proof_of_address"] else identity
            documents.remove(late)
        payload = {
            "applicant_name": name,
            "date_of_birth": born.isoformat(),
            "country_code": country,
            "account_type": "current" if rng.random() < 0.75 else "savings",
            "documents": documents,
            "politically_exposed": kind == "politically_exposed",
            "expected_monthly_deposits": rng.choice([60_000, 120_000])
            if kind == "politically_exposed"
            else rng.randint(0, 20_000),
            "_late_document": late,
        }
        return SyntheticApplication(
            index=index,
            kind=kind,
            expected_outcome="rejected" if kind in SHOULD_REJECT else "approved",
            arrival_offset_seconds=rng.randint(0, self.window),
            document_delay_seconds=rng.randint(*self.delay)
            if kind == "missing_documents"
            else None,
            payload=payload,
        )


@dataclass(frozen=True)
class SyntheticStaffMember:
    index: int
    role: str  # teller | manager | compliance | executive
    first_name: str
    last_name: str
    job_title: str


JOB_TITLES = {
    "teller": "Customer Onboarding Officer",
    "manager": "Onboarding Team Manager",
    "compliance": "KYC Compliance Analyst",
}


class StaffGenerator:
    def __init__(
        self, seed: int, staff_mix: dict[str, float], job_titles: dict[str, str] | None = None
    ) -> None:
        self.seed = seed
        self.mix = staff_mix
        self.titles = job_titles or JOB_TITLES

    def generate(self, count: int) -> list[SyntheticStaffMember]:
        roles = sorted(self.mix)
        total = sum(self.mix.values())
        # Deterministic allocation by largest remainder; at least one of each role.
        exact = {r: count * self.mix[r] / total for r in roles}
        counts = {r: max(1, int(exact[r])) for r in roles}
        for r in sorted(roles, key=lambda r: exact[r] - int(exact[r]), reverse=True):
            if sum(counts.values()) >= count:
                break
            counts[r] += 1
        members = []
        for role in roles:
            for _ in range(counts[role]):
                rng = case_random(self.seed, len(members), "staff")
                members.append(
                    SyntheticStaffMember(
                        index=len(members),
                        role=role,
                        first_name=rng.choice(FIRST_NAMES),
                        last_name=rng.choice(LAST_NAMES),
                        job_title=self.titles[role],
                    )
                )
        return members


def digest(rows: list) -> str:
    """Stable fingerprint of a result set (used to verify reproducibility)."""
    import json

    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()
