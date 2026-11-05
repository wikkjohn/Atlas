"""Scoped access (Phase 84): a user may be limited to countries and departments.

A dimension without entries does not limit; a record without the attribute (a customer has
no department) is not limited by that dimension. Permissions still decide what a user may
do; the scope decides where.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Scope:
    countries: frozenset[str] | None = None  # ISO 3166 alpha-2 codes
    departments: frozenset[str] | None = None  # department names, as in the catalogue

    @property
    def limited(self) -> bool:
        return self.countries is not None or self.departments is not None

    def allows_country(self, code: str | None) -> bool:
        return self.countries is None or code is None or code in self.countries

    def allows_department(self, name: str | None) -> bool:
        return self.departments is None or name is None or name in self.departments

    def describe(self) -> dict[str, list[str] | None]:
        return {
            "countries": sorted(self.countries) if self.countries is not None else None,
            "departments": sorted(self.departments) if self.departments is not None else None,
        }


UNRESTRICTED = Scope()
